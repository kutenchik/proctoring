import json

import pytest

from proctoring.exam import Quiz


def write_quiz(tmp_path, questions):
    path = tmp_path / "quiz.json"
    path.write_text(json.dumps({"questions": questions}), encoding="utf-8")
    return path


def question(**changes):
    return {"id": "q1", "prompt": "2 + 2?", "options": ["3", "4"],
            "correct_index": 1, **changes}


def test_quiz_scores_and_replaces_answers(tmp_path):
    quiz = Quiz.from_file(write_quiz(tmp_path, [question(), question(id="q2")]))
    assert quiz.total == 2
    assert quiz.score == quiz.answered_count == 0
    quiz.answer(0, 0)
    assert quiz.score == 0
    assert quiz.answered_count == 1
    quiz.answer(0, 1)
    quiz.answer(1, 1)
    assert quiz.score == 2
    assert quiz.answered_count == 2
    assert quiz.answers == {0: 1, 1: 1}
    quiz.answers.clear()
    assert quiz.answered_count == 2


@pytest.mark.parametrize("index,option", [(-1, 0), (1, 0), (False, 0), (0, -1), (0, 2), (0, True)])
def test_quiz_rejects_invalid_answers(tmp_path, index, option):
    quiz = Quiz.from_file(write_quiz(tmp_path, [question()]))
    with pytest.raises(IndexError):
        quiz.answer(index, option)
    assert quiz.answered_count == 0


@pytest.mark.parametrize("questions", [
    [], [None], [question(), question()], [question(id="")], [question(id=1)],
    [question(prompt="  ")], [question(options=["only one"])],
    [question(options=["one", " "])], [question(options="not a list")],
    [question(correct_index=True)], [question(correct_index=2)],
    [question(correct_index=-1)], [question(correct_index="1")],
])
def test_quiz_rejects_invalid_question_data(tmp_path, questions):
    with pytest.raises(ValueError):
        Quiz.from_file(write_quiz(tmp_path, questions))


@pytest.mark.parametrize("data", [[], {}, {"questions": "invalid"}])
def test_quiz_rejects_invalid_file_shape(tmp_path, data):
    path = tmp_path / "quiz.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        Quiz.from_file(path)
