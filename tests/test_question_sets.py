"""Focused Stage 1 imports, stable IDs and exact-set scoring; no devices."""
from copy import deepcopy
import random

import pytest

from proctoring.exam.quiz import Quiz, normalize_question_set


def document():
    return {"title": "Number skills", "questions": [
        {"id": "sum", "type": "single_choice", "prompt": "2+2?",
         "options": [{"id": "three", "text": "3"}, {"id": "four", "text": "4"}],
         "correct_option_ids": ["four"]},
        {"id": "even", "type": "multiple_choice", "prompt": "Select all even numbers",
         "options": [{"id": "two", "text": "2"}, {"id": "three", "text": "3"}, {"id": "four", "text": "4"}],
         "correct_option_ids": ["two", "four"]}]}


def test_shared_exact_set_scoring_and_revision():
    quiz = Quiz.from_document(document())
    quiz.answer(0, 1)
    quiz.answer(1, [0])
    assert quiz.score == 1
    quiz.answer(1, [2, 0])
    assert quiz.score == 2 and quiz.percentage == 100
    assert quiz.answers == {0: 1, 1: [0, 2]}
    quiz.answers[1].clear()
    assert quiz.score == 2
    quiz.answer(1, [0, 1, 2])
    assert quiz.score == 1  # no partial credit
    quiz.answer(1, [])
    assert quiz.answered_count == 1


@pytest.mark.parametrize("bad", [True, 1, [False], [-1], [3], [0, 0], ["two"], None])
def test_multiple_choice_rejects_invalid_selections(bad):
    quiz = Quiz.from_document(document())
    with pytest.raises(IndexError):
        quiz.answer(1, bad)
    assert quiz.answers == {}


def test_shuffle_preserves_id_key_mapping_and_input():
    data = document()
    before = deepcopy(data)
    quiz = Quiz.from_document(data, shuffle_questions=True, shuffle_options=True, rng=random.Random(3))
    for i, question in enumerate(quiz.questions):
        indices = [question.option_ids.index(key) for key in question.correct_option_ids]
        quiz.answer(i, indices[0] if question.type == "single_choice" else indices)
    assert quiz.score == 2
    assert quiz.answer_ids["sum"] == ["four"]
    assert set(quiz.answer_ids["even"]) == {"two", "four"}
    assert data == before
    restored = Quiz.from_document(quiz.to_document())
    assert restored.questions == quiz.questions
    assert restored.answers == {}


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(title=""),
    lambda d: d["questions"][0].update(type="essay"),
    lambda d: d["questions"][0].update(correct_option_ids=["missing"]),
    lambda d: d["questions"][0].update(correct_option_ids=["three", "four"]),
    lambda d: d["questions"][1].update(correct_option_ids=[]),
    lambda d: d["questions"][1].update(correct_option_ids=["two", "two"]),
    lambda d: d["questions"][1].update(id="sum"),
    lambda d: d["questions"][0]["options"][1].update(id="three"),
    lambda d: d["questions"][0].update(points=2),
    lambda d: d["questions"][0].update(points=True),
    lambda d: d["questions"][0].update(id="../bad"),
    lambda d: d["questions"][0].update(prompt="x" * 4001),
    lambda d: d.update(questions=d["questions"] * 101),
])
def test_normalization_rejects_invalid_imports(mutation):
    data = document()
    mutation(data)
    with pytest.raises(ValueError):
        normalize_question_set(data)


def test_normalization_detaches_original():
    original = document()
    normalized = normalize_question_set(original)
    normalized["questions"][0]["options"][0]["text"] = "changed"
    assert original["questions"][0]["options"][0]["text"] == "3"


def test_no_answers_are_zero_points():
    quiz = Quiz.from_document(document())
    assert quiz.score == 0 and quiz.percentage == 0


def test_display_payload_limit_is_validated_before_admission():
    data = document()
    data['questions'] = [dict(data['questions'][0], id=f'q{i}', prompt='Ә' * 3900) for i in range(10)]
    with pytest.raises(ValueError, match='64 KiB'):
        normalize_question_set(data)
