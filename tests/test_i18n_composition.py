"""Real composed status labels must translate every visible presentation part."""
import pytest

from proctoring.domain import EVENT_LABELS, EventType
from proctoring.i18n import manager, translate_text


@pytest.fixture(autouse=True)
def reset_locale():
    manager.set_language("en")
    yield
    manager.set_language("en")


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_complete_camera_metrics_localize_each_line(language):
    source = (
        "Capture 30.0 FPS · Monitoring 10.0 FPS\n"
        "YOLO 85 ms · Face landmarks 20 ms · CPUExecutionProvider\n"
        "YOLO input: 416\nSource: 640×480 px (requested 1280×720)"
    )
    manager.set_language(language)
    rendered = translate_text(source)
    assert rendered.count("\n") == source.count("\n")
    for english in ("Capture", "Monitoring", "Face landmarks", "YOLO input", "Source:", "requested"):
        assert english not in rendered
    for preserved in ("30.0", "10.0", "85", "20", "CPUExecutionProvider", "416", "640×480", "1280×720"):
        assert preserved in rendered


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_live_gaze_people_face_and_pose_compose_without_english_tail(language):
    source = (
        "Eye-gaze estimate: DOWN · People: 1 · Face: present\n"
        "Head pose · yaw 3° · pitch -2° · roll 1°"
    )
    manager.set_language(language)
    rendered = translate_text(source)
    for english in ("Eye-gaze estimate", "DOWN", "People:", "Face:", "present", "Head pose", "yaw", "pitch", "roll"):
        assert english not in rendered
    assert "3°" in rendered and "-2°" in rendered and "1°" in rendered


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_complete_session_summary_localizes_beyond_first_line(language):
    source = (
        "Score: 2 / 6\nAnswered: 3 questions   •   Active exam time: 42.5s\n"
        "Review events: 2   •   End reason: proctor_ended\n\n"
        "Monitoring stopped. Protection interface released. No Windows restrictions were installed."
    )
    manager.set_language(language)
    rendered = translate_text(source)
    for english in ("Score:", "Answered:", "questions", "Active exam time", "Review events", "End reason", "Monitoring stopped", "Protection interface"):
        assert english not in rendered
    assert "2 / 6" in rendered and "42.5" in rendered
    assert rendered.count("\n") == source.count("\n")


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_event_list_translates_all_rows_and_keeps_canonical_event_values(language):
    events = [EventType.PHONE_VISIBLE, EventType.SECOND_PERSON, EventType.FACE_ABSENT]
    source = "\n".join(f"{EVENT_LABELS[event]}: {index + 1}" for index, event in enumerate(events))
    manager.set_language(language)
    rendered = translate_text(source)
    expected = "\n".join(f"{translate_text(EVENT_LABELS[event])}: {index + 1}" for index, event in enumerate(events))
    assert rendered == expected
    for event in events:
        assert EVENT_LABELS[event] not in rendered
    assert [event.value for event in events] == ["phone_visible", "second_person", "face_absent"]


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_unobservable_eyes_translate_without_dropping_both_quality_reasons(language):
    source = (
        "Eye-gaze estimate: UNKNOWN · People: 1 · Face: present\n"
        "Gaze availability reduced · left: low eyelid aperture; iris visibility unverified; "
        "right: iris outside plausible eye geometry\n"
        "Head pose · yaw 3° · pitch -2° · roll 1°"
    )
    manager.set_language(language)
    rendered = translate_text(source)
    for english in ("Eye-gaze estimate", "UNKNOWN", "People:", "Face:", "Gaze availability", "low eyelid aperture", "iris visibility unverified", "iris outside plausible", "Head pose"):
        assert english not in rendered
    assert rendered.count("\n") == source.count("\n")


def test_english_compositions_remain_byte_for_byte_unchanged():
    source = "Eye-gaze estimate: UNKNOWN · People: 1 · Face: present\nHead pose · yaw 3° · pitch -2° · roll 1°"
    assert translate_text(source) == source
