"""Shared Python quiz validation and exact-set scoring, independent of any UI."""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
import random
import re

MAX_QUESTIONS = 200
MAX_OPTIONS = 20
MAX_PUBLIC_QUIZ_BYTES = 64 * 1024
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')


def _text(value, name, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{name} must be nonempty text of at most {limit} characters')
    return value.strip()


def _identifier(value, name):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f'{name} must be a stable ID (1-64 ASCII letters, digits, _ or -)')
    return value


def normalize_question_set(data: dict) -> dict:
    """Validate imported questions; never infer keys, points or stable IDs."""
    if not isinstance(data, dict):
        raise ValueError('Question set must be an object')
    title = _text(data.get('title'), 'Question set title', 200)
    items = data.get('questions')
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_QUESTIONS:
        raise ValueError(f'Question set must contain 1-{MAX_QUESTIONS} questions')
    ids, questions = set(), []
    for number, item in enumerate(items, 1):
        prefix = f'Question {number}'
        if not isinstance(item, dict):
            raise ValueError(f'{prefix} must be an object')
        qid = _identifier(item.get('id'), f'{prefix} id')
        if qid in ids:
            raise ValueError(f'Duplicate question id: {qid}')
        ids.add(qid)
        kind = item.get('type')
        if kind not in ('single_choice', 'multiple_choice'):
            raise ValueError(f'{prefix} type must be single_choice or multiple_choice')
        prompt = _text(item.get('prompt'), f'{prefix} prompt', 4000)
        raw_options = item.get('options')
        if not isinstance(raw_options, list) or not 2 <= len(raw_options) <= MAX_OPTIONS:
            raise ValueError(f'{prefix} must have 2-{MAX_OPTIONS} options')
        options, option_ids = [], set()
        for option in raw_options:
            if not isinstance(option, dict):
                raise ValueError(f'{prefix} options must contain id and text')
            oid = _identifier(option.get('id'), f'{prefix} option id')
            if oid in option_ids:
                raise ValueError(f'{prefix} has duplicate option id: {oid}')
            option_ids.add(oid)
            options.append({'id': oid, 'text': _text(option.get('text'), f'{prefix} option text', 2000)})
        correct = item.get('correct_option_ids')
        if (not isinstance(correct, list) or not correct or
                any(not isinstance(key, str) or key not in option_ids for key in correct) or
                len(set(correct)) != len(correct)):
            raise ValueError(f'{prefix} correct_option_ids must contain unique existing option IDs')
        if kind == 'single_choice' and len(correct) != 1:
            raise ValueError(f'{prefix} single choice requires exactly one correct option')
        if 'points' in item and (type(item['points']) is not int or item['points'] != 1):
            raise ValueError(f'{prefix} is worth exactly one point')
        questions.append({'id': qid, 'type': kind, 'prompt': prompt, 'options': options,
                          'correct_option_ids': [o['id'] for o in options if o['id'] in correct]})
    # Reject at import time, before admission consumes the single-attempt slot.
    # The existing bounded IPC also carries calibration/monitoring metadata.
    public = [{'id': q['id'], 'type': q['type'], 'prompt': q['prompt'],
               'options': [o['text'] for o in q['options']],
               'option_ids': [o['id'] for o in q['options']]} for q in questions]
    if len(json.dumps(public, ensure_ascii=False).encode('utf-8')) > MAX_PUBLIC_QUIZ_BYTES:
        raise ValueError('Question set exceeds the 64 KiB desktop display-content limit; split it into smaller sets')
    return {'title': title, 'questions': questions}


@dataclass(frozen=True)
class Question:
    id: str
    prompt: str
    options: tuple[str, ...]
    correct_index: int | None
    type: str = 'single_choice'
    option_ids: tuple[str, ...] = ()
    correct_option_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.option_ids:
            object.__setattr__(self, 'option_ids', tuple(f'o{i+1}' for i in range(len(self.options))))
        if not self.correct_option_ids and self.correct_index is not None:
            object.__setattr__(self, 'correct_option_ids', (self.option_ids[self.correct_index],))


class Quiz:
    def __init__(self, questions: list[Question], *, title='Quiz'):
        if not questions:
            raise ValueError('Quiz must contain at least one question')
        self.questions = tuple(questions)
        self.title = title
        self._answers: dict[int, int | tuple[int, ...]] = {}

    @classmethod
    def from_file(cls, path: Path) -> Quiz:
        with Path(path).open(encoding='utf-8') as source:
            return cls.from_document(json.load(source))

    @classmethod
    def from_document(cls, data: dict, *, shuffle_questions=False, shuffle_options=False, rng=None) -> Quiz:
        if not isinstance(data, dict) or not isinstance(data.get('questions'), list):
            raise ValueError('Quiz must be an object containing a questions list')
        if data['questions'] and all(isinstance(q, dict) and 'type' in q for q in data['questions']):
            normalized = normalize_question_set(data)
            questions = []
            for item in normalized['questions']:
                options = list(item['options'])
                if shuffle_options:
                    (rng or random.SystemRandom()).shuffle(options)
                ids = tuple(o['id'] for o in options)
                correct = tuple(item['correct_option_ids'])
                questions.append(Question(item['id'], item['prompt'], tuple(o['text'] for o in options),
                                          ids.index(correct[0]) if item['type'] == 'single_choice' else None,
                                          item['type'], ids, correct))
            if shuffle_questions:
                (rng or random.SystemRandom()).shuffle(questions)
            return cls(questions, title=normalized['title'])
        # Legacy standalone files retain their original schema and validation.
        questions, ids = [], set()
        for index, item in enumerate(data['questions']):
            prefix = f'Question {index+1}'
            if not isinstance(item, dict):
                raise ValueError(f'{prefix} must be an object')
            if 'type' in item:
                raise ValueError('Do not mix legacy and imported question formats')
            question_id = item.get('id')
            if not isinstance(question_id, str) or not question_id.strip():
                raise ValueError(f'{prefix} must have a nonempty string id')
            if question_id in ids:
                raise ValueError(f'Duplicate question id: {question_id}')
            prompt = item.get('prompt')
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError(f'{prefix} must have a nonempty prompt')
            options = item.get('options')
            if (not isinstance(options, list) or len(options) < 2 or
                    any(not isinstance(option, str) or not option.strip() for option in options)):
                raise ValueError(f'{prefix} must have at least two nonempty options')
            correct = item.get('correct_index')
            if type(correct) is not int or not 0 <= correct < len(options):
                raise ValueError(f'{prefix} correct_index is outside the options')
            ids.add(question_id)
            questions.append(Question(question_id, prompt, tuple(options), correct))
        return cls(questions, title=data.get('title', 'Quiz'))

    def to_document(self) -> dict:
        """Trusted Python/server use only. Includes answer keys, never renderer data."""
        return {'title': self.title, 'questions': [
            {'id': q.id, 'type': q.type, 'prompt': q.prompt,
             'options': [{'id': oid, 'text': text} for oid, text in zip(q.option_ids, q.options)],
             'correct_option_ids': list(q.correct_option_ids)} for q in self.questions]}

    @property
    def answers(self) -> dict[int, int | list[int]]:
        return {i: list(a) if isinstance(a, tuple) else a for i, a in self._answers.items()}

    @property
    def answer_ids(self) -> dict[str, list[str]]:
        return {self.questions[i].id: [self.questions[i].option_ids[o] for o in
                ((a,) if type(a) is int else a)] for i, a in self._answers.items()}

    def answer(self, index: int, option: int | list[int]) -> None:
        if type(index) is not int or not 0 <= index < len(self.questions):
            raise IndexError('Question index is outside the quiz')
        q = self.questions[index]
        if q.type == 'single_choice':
            if type(option) is not int or not 0 <= option < len(q.options):
                raise IndexError('Answer index is outside the question options')
            self._answers[index] = option
        else:
            if (not isinstance(option, list) or
                    any(type(o) is not int or not 0 <= o < len(q.options) for o in option) or
                    len(set(option)) != len(option)):
                raise IndexError('Multiple choice requires unique option indices')
            if option:
                self._answers[index] = tuple(sorted(option))
            else:
                self._answers.pop(index, None)

    @property
    def score(self) -> int:
        selected = self.answer_ids
        return sum(set(selected.get(q.id, [])) == set(q.correct_option_ids) for q in self.questions)

    @property
    def percentage(self) -> float:
        return self.score * 100 / self.total

    @property
    def total(self) -> int:
        return len(self.questions)

    @property
    def answered_count(self) -> int:
        return len(self._answers)
