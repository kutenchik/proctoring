"""Small validated quiz model with no dependency on the UI."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class Question:
    id: str
    prompt: str
    options: tuple[str, ...]
    correct_index: int


class Quiz:
    def __init__(self, questions: list[Question]):
        if not questions:
            raise ValueError("Quiz must contain at least one question")
        self.questions = tuple(questions)
        self._answers: dict[int, int] = {}

    @classmethod
    def from_file(cls, path: Path) -> Quiz:
        with Path(path).open(encoding="utf-8") as source:
            data = json.load(source)
        if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
            raise ValueError("Quiz must be an object containing a questions list")
        questions = []
        ids: set[str] = set()
        for index, item in enumerate(data["questions"]):
            prefix = f"Question {index + 1}"
            if not isinstance(item, dict):
                raise ValueError(f"{prefix} must be an object")
            question_id = item.get("id")
            if not isinstance(question_id, str) or not question_id.strip():
                raise ValueError(f"{prefix} must have a nonempty string id")
            if question_id in ids:
                raise ValueError(f"Duplicate question id: {question_id}")
            prompt = item.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError(f"{prefix} must have a nonempty prompt")
            options = item.get("options")
            if (not isinstance(options, list) or len(options) < 2
                    or any(not isinstance(option, str) or not option.strip()
                           for option in options)):
                raise ValueError(f"{prefix} must have at least two nonempty options")
            correct = item.get("correct_index")
            if type(correct) is not int or not 0 <= correct < len(options):
                raise ValueError(f"{prefix} correct_index is outside the options")
            ids.add(question_id)
            questions.append(Question(question_id, prompt, tuple(options), correct))
        return cls(questions)

    @property
    def answers(self) -> dict[int, int]:
        return dict(self._answers)

    def answer(self, index: int, option: int) -> None:
        if type(index) is not int or not 0 <= index < len(self.questions):
            raise IndexError("Question index is outside the quiz")
        if type(option) is not int or not 0 <= option < len(self.questions[index].options):
            raise IndexError("Answer index is outside the question options")
        self._answers[index] = option

    @property
    def score(self) -> int:
        return sum(option == self.questions[index].correct_index
                   for index, option in self._answers.items())

    @property
    def total(self) -> int:
        return len(self.questions)

    @property
    def answered_count(self) -> int:
        return len(self._answers)
