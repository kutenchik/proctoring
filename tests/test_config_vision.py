"""Reject invalid performance/calibration settings before starting workers."""
import pytest

from proctoring.config import DEFAULT_CONFIG, load_config


def test_vision_defaults_are_cpu_first_and_models_resolve_locally():
    config = load_config()
    assert config.vision.capture_width == 1280
    assert config.vision.capture_height == 720
    assert config.vision.camera_index == 0
    assert config.vision.prefer_gpu is False
    assert config.vision.yolo_model.is_absolute()
    assert config.vision.face_model.is_absolute()
    assert config.vision.calibration_samples >= 5
    assert config.vision.calibration_preparation_seconds == 2.
    assert config.vision.calibration_collection_seconds == 3.
    assert config.vision.calibration_debug is False
    assert config.vision.calibration_pixel_uncertainty_multiplier == .8
    assert config.vision.face_fps > config.vision.yolo_fps
    assert config.public_dict()["vision"]["yolo_model"] == str(config.vision.yolo_model)
    assert config.vision.alignment.stable_seconds == .75
    assert config.vision.alignment.min_eye_width_pixels == 32
    assert config.vision.alignment.guide == (.18, .08, .82, .92)
    assert config.vision.head_down_pitch_degrees == 14.
    assert config.vision.head_down_max_yaw_degrees == 15.
    assert config.vision.head_down_max_roll_degrees == 12.


def test_alignment_overrides_merge_defaults_without_changing_gaze_gates(tmp_path):
    text = DEFAULT_CONFIG.with_name("default.example.toml").read_text(encoding="utf-8")
    text = text[:text.index("[vision.alignment]")] + "[vision.alignment]\nstable_seconds = 1.0\n"
    path = tmp_path / "alignment.toml"
    path.write_text(text, encoding="utf-8")
    config = load_config(path)
    assert config.vision.alignment.stable_seconds == 1.
    assert config.vision.alignment.min_eye_width_pixels == 32.
    assert config.vision.calibration_min_signal_noise == 3.
    assert config.vision.calibration_eye_noise_floor == .01


@pytest.mark.parametrize("settings", [
    "stable_seconds = 0", "stable_seconds = nan", "stable_seconds = true",
    "min_stable_samples = 2", "min_stable_samples = true",
    'guide = [0.1, 0.2, 0.3]', 'guide = [0.9, 0.1, 0.2, 0.9]',
    'guide = [0.1, 0.1, 1.1, 0.9]', 'min_eye_width_pixels = "small"',
    "unknown_setting = 1", "max_pitch_degrees = -1",
])
def test_invalid_alignment_configuration_fails_before_startup(tmp_path, settings):
    text = DEFAULT_CONFIG.with_name("default.example.toml").read_text(encoding="utf-8")
    path = tmp_path / "alignment.toml"
    path.write_text(text[:text.index("[vision.alignment]")] + "[vision.alignment]\n" + settings,
                    encoding="utf-8")
    with pytest.raises(ValueError, match="alignment"):
        load_config(path)


@pytest.mark.parametrize("old,new", [
    ("camera_index = 0", "camera_index = -1"),
    ("camera_index = 0", "camera_index = true"),
    ("capture_width = 1280", "capture_width = 0"),
    ("capture_height = 720", "capture_height = 720.5"),
    ("yolo_input_size = 416", "yolo_input_size = 415"),
    ("yolo_input_size = 416", "yolo_input_size = 96"),
    ("yolo_fps = 5.0", "yolo_fps = 0"),
    ("face_fps = 12.0", "face_fps = nan"),
    ("cpu_threads = 2", "cpu_threads = 0"),
    ("prefer_gpu = false", 'prefer_gpu = "true"'),
    ('camera_backend = "auto"', 'camera_backend = "unknown"'),
    ("phone_confidence = 0.35", "phone_confidence = 1.01"),
    ("person_min_area = 0.015", "person_min_area = -1"),
    ("person_min_height = 0.12", "person_min_height = 1.2"),
    ("calibration_samples = 20", "calibration_samples = 4"),
    ("calibration_max_spread = 0.12", "calibration_max_spread = inf"),
    ("calibration_max_samples = 240", "calibration_max_samples = 19"),
    ("calibration_max_samples = 240", "calibration_max_samples = 999999"),
    ("calibration_debug = false", 'calibration_debug = "true"'),
    ("calibration_preparation_seconds = 2.0", "calibration_preparation_seconds = 0.1"),
    ("calibration_collection_seconds = 3.0", "calibration_collection_seconds = 0.2"),
    ("calibration_collection_seconds = 3.0", "calibration_collection_seconds = 60.0"),
    ("calibration_collection_seconds = 3.0", "calibration_collection_seconds = 1.0"),
    ("calibration_eye_noise_floor = 0.01", "calibration_eye_noise_floor = 0.0"),
    ("calibration_min_signal_noise = 3.0", "calibration_min_signal_noise = 1.0"),
    ("calibration_pixel_uncertainty_multiplier = 0.8", "calibration_pixel_uncertainty_multiplier = 0.0"),
    ("calibration_pixel_uncertainty_multiplier = 0.8", "calibration_pixel_uncertainty_multiplier = -0.8"),
    ("calibration_pixel_uncertainty_multiplier = 0.8", "calibration_pixel_uncertainty_multiplier = nan"),
    ("calibration_pixel_uncertainty_multiplier = 0.8", "calibration_pixel_uncertainty_multiplier = true"),
    ("calibration_center_radius_fraction = 0.45", "calibration_center_radius_fraction = 0.6"),
    ("calibration_offscreen_radius_fraction = 0.30", "calibration_offscreen_radius_fraction = 0.7"),
    ("result_stale_seconds = 2.0", "result_stale_seconds = 0.2"),
    ("heartbeat_stale_seconds = 5.0", "heartbeat_stale_seconds = false"),
    ("raised_person_top_fraction = 0.45", "raised_person_top_fraction = 1.5"),
    ("camera_index = 0", "camera_index = 0\nunknown_camera_setting = 1"),
])
def test_invalid_vision_settings_fail_before_workers(tmp_path, old, new):
    text = DEFAULT_CONFIG.with_name("default.example.toml").read_text(encoding="utf-8")
    assert old in text
    path = tmp_path / "config.toml"
    path.write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)


@pytest.mark.parametrize("key,default", [
    ("head_down_pitch_degrees", "14.0"),
    ("head_down_max_yaw_degrees", "15.0"),
    ("head_down_max_roll_degrees", "12.0"),
])
@pytest.mark.parametrize("value", ["0", "-1", "90", "180", "nan", "inf", "true"])
def test_invalid_head_down_pose_settings_fail_before_workers(tmp_path, key, default, value):
    text = DEFAULT_CONFIG.with_name("default.example.toml").read_text(encoding="utf-8")
    path = tmp_path / "pose.toml"
    path.write_text(text.replace(f"{key} = {default}", f"{key} = {value}"), encoding="utf-8")
    with pytest.raises(ValueError, match=key):
        load_config(path)
