from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from proctoring.vision.settings import VisionConfig
from proctoring.vision.yolo import Letterbox, YoloDetector, decode, preprocess


def predictions(rows):
    result = np.zeros((1, 84, len(rows)), dtype=np.float32)
    for index, (xywh, class_id, confidence) in enumerate(rows):
        result[0, :4, index] = xywh
        result[0, class_id + 4, index] = confidence
    return result


def test_preprocess_letterboxes_rgb_float32_without_distortion():
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[:] = [10, 20, 30]
    tensor, geometry = preprocess(image, 416, 416)
    assert tensor.shape == (1, 3, 416, 416)
    assert tensor.dtype == np.float32
    assert tensor.flags.c_contiguous
    assert geometry.scale == pytest.approx(.325)
    assert geometry.left == 0 and geometry.top == 91
    assert tensor[0, :, 208, 208] == pytest.approx(np.array([30, 20, 10]) / 255)
    assert tensor[0, :, 0, 0] == pytest.approx(np.array([114] * 3) / 255)


def test_decode_undoes_padding_and_returns_normalized_boxes():
    config = VisionConfig()
    data = predictions([((208, 208, 208, 117), 0, .8), ((300, 180, 30, 60), 67, .7)])
    persons, phones = decode(data, Letterbox(.325, 0, 91, 1280, 720), config)
    assert len(persons) == len(phones) == 1
    assert (persons[0].x1, persons[0].y1, persons[0].x2, persons[0].y2) == pytest.approx((.25, .25, .75, .75))
    assert phones[0].class_id == 67


def test_decode_per_class_nms_keeps_phone_overlapping_person():
    data = predictions([((200, 200, 100, 100), 0, .9), ((201, 201, 100, 100), 0, .8),
                        ((200, 200, 100, 100), 67, .75)])
    persons, phones = decode(data, Letterbox(1, 0, 0, 416, 416), VisionConfig())
    assert len(persons) == len(phones) == 1
    assert persons[0].confidence == pytest.approx(.9)


def test_decode_filters_tiny_people_low_confidence_and_unwanted_classes():
    data = predictions([((100, 100, 2, 2), 0, .95), ((100, 100, 100, 100), 0, .4),
                        ((200, 200, 100, 100), 67, .3), ((200, 200, 100, 100), 2, .95)])
    assert decode(data, Letterbox(1, 0, 0, 416, 416), VisionConfig()) == ((), ())


def test_decode_rejects_invalid_numbers_and_zero_boxes():
    data = predictions([((100, 100, 0, 100), 0, .9), ((float("nan"), 200, 100, 100), 0, .9)])
    assert decode(data, Letterbox(1, 0, 0, 416, 416), VisionConfig()) == ((), ())


def test_decode_supports_transposed_output():
    data = predictions([((200, 200, 100, 100), 0, .8)]).transpose(0, 2, 1)
    assert len(decode(data, Letterbox(1, 0, 0, 416, 416), VisionConfig())[0]) == 1


def test_decode_requires_raw_coco_output():
    with pytest.raises(ValueError, match="nms=False"):
        decode(np.zeros((1, 300, 6)), Letterbox(1, 0, 0, 416, 416), VisionConfig())


class Session:
    def __init__(self, shape):
        self.shape = shape
        self.tensor = None

    def get_inputs(self):
        return [SimpleNamespace(shape=self.shape, type="tensor(float)", name="images")]

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def run(self, outputs, inputs):
        self.tensor = inputs["images"]
        return [np.zeros((1, 84, 0), dtype=np.float32)]


@pytest.mark.parametrize("shape,expected", [([1, 3, 640, 640], 640), ([1, 3, "height", "width"], 416)])
def test_detector_honors_fixed_model_and_configures_dynamic_size(shape, expected):
    session = Session(shape)
    detector = YoloDetector(VisionConfig(yolo_input_size=416), session=session)
    assert detector.detect(np.zeros((720, 1280, 3), dtype=np.uint8)) == ((), ())
    assert session.tensor.shape == (1, 3, expected, expected)
    assert detector.provider == "CPUExecutionProvider"


def test_missing_model_never_attempts_download(tmp_path):
    with pytest.raises(FileNotFoundError, match="Local YOLO model missing"):
        YoloDetector(replace(VisionConfig(), yolo_model=tmp_path / "missing.onnx"))


@pytest.mark.parametrize("shape", [[2, 3, 416, 416], [1, 1, 416, 416], [1, 3, 416]])
def test_invalid_model_inputs_rejected(shape):
    with pytest.raises(ValueError):
        YoloDetector(VisionConfig(), session=Session(shape))


@pytest.mark.parametrize("prefer_gpu,expected_calls", [
    (False, [["CPUExecutionProvider"]]),
    (True, [["CUDAExecutionProvider", "CPUExecutionProvider"], ["CPUExecutionProvider"]]),
])
def test_cpu_default_and_unusable_gpu_initialization_falls_back(tmp_path, monkeypatch, prefer_gpu, expected_calls):
    import sys
    model = tmp_path / "local.onnx"
    model.write_bytes(b"fake test model")
    calls = []
    def create(path, sess_options, providers):
        calls.append(providers)
        assert sess_options.intra_op_num_threads == 2
        if "CUDAExecutionProvider" in providers:
            raise RuntimeError("GPU runtime unavailable")
        return Session([1, 3, 416, 416])
    ort = SimpleNamespace(SessionOptions=SimpleNamespace,
                          GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL=99),
                          InferenceSession=create,
                          get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    detector = YoloDetector(replace(VisionConfig(), yolo_model=model, prefer_gpu=prefer_gpu))
    assert calls == expected_calls
    assert detector.provider == "CPUExecutionProvider"


def test_gpu_execution_failure_retries_on_cpu(monkeypatch):
    import proctoring.vision.yolo as module
    class GpuSession(Session):
        def get_providers(self): return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        def run(self, outputs, inputs): raise RuntimeError("CUDA execution failed")
    detector = YoloDetector(VisionConfig(), session=GpuSession([1, 3, 416, 416]))
    detector._ort = object()
    cpu_session = Session([1, 3, 416, 416])
    monkeypatch.setattr(detector, "_create_session", lambda providers: cpu_session)
    monkeypatch.setattr(module, "preprocess", lambda *args: (
        np.zeros((1, 3, 416, 416), dtype=np.float32), Letterbox(1, 0, 0, 416, 416)))
    assert detector.detect(object()) == ((), ())
    assert detector.provider == "CPUExecutionProvider"
    assert detector.session is cpu_session
