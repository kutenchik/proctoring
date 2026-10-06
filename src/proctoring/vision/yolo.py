"""Local YOLO11 detection using ONNX Runtime, with no network or Ultralytics runtime."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .settings import VisionConfig
from .types import Box


@dataclass(frozen=True)
class Letterbox:
    scale: float
    left: int
    top: int
    source_width: int
    source_height: int


def preprocess(frame, input_width: int, input_height: int):
    import cv2
    import numpy as np
    if frame is None or frame.ndim != 3 or frame.shape[2] != 3 or not frame.size:
        raise ValueError("YOLO expects a nonempty HWC BGR image")
    source_height, source_width = frame.shape[:2]
    ratio = min(input_width / source_width, input_height / source_height)
    resized_width = max(1, round(source_width * ratio))
    resized_height = max(1, round(source_height * ratio))
    resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
    pad_w, pad_h = input_width - resized_width, input_height - resized_height
    left, top = round(pad_w / 2 - .1), round(pad_h / 2 - .1)
    padded = cv2.copyMakeBorder(resized, top, pad_h - top, left, pad_w - left,
                               cv2.BORDER_CONSTANT, value=(114, 114, 114))
    tensor = np.ascontiguousarray(padded[..., ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
    return tensor, Letterbox(ratio, left, top, source_width, source_height)


def _nms(boxes: list[Box], threshold: float) -> tuple[Box, ...]:
    # Only person and phone classes survive decoding. Cap candidates to bound work.
    pending = sorted(boxes, key=lambda box: box.confidence, reverse=True)[:1000]
    kept: list[Box] = []
    while pending and len(kept) < 300:
        current = pending.pop(0)
        kept.append(current)
        survivors = []
        for other in pending:
            intersection = (max(0.0, min(current.x2, other.x2) - max(current.x1, other.x1))
                            * max(0.0, min(current.y2, other.y2) - max(current.y1, other.y1)))
            union = current.area + other.area - intersection
            if union <= 0 or intersection / union <= threshold:
                survivors.append(other)
        pending = survivors
    return tuple(kept)


def decode(output, transform: Letterbox, config: VisionConfig) -> tuple[tuple[Box, ...], tuple[Box, ...]]:
    import numpy as np
    data = np.asarray(output)
    if data.ndim == 3:
        if data.shape[0] != 1:
            raise ValueError("YOLO output must have batch size one")
        data = data[0]
    if data.ndim != 2:
        raise ValueError(f"Unsupported YOLO output shape {data.shape}; expected [1,84,N]")
    if data.shape[0] == 84:
        data = data.T
    elif data.shape[1] != 84:
        raise ValueError(f"Unsupported YOLO output shape {data.shape}; export raw COCO output with nms=False")
    if not len(data):
        return (), ()
    data = data[np.all(np.isfinite(data), axis=1)]
    if not len(data):
        return (), ()
    classes = np.argmax(data[:, 4:], axis=1)
    confidences = data[np.arange(len(data)), classes + 4]
    wanted = ((classes == 0) & (confidences >= config.person_confidence)) | ((classes == 67) & (confidences >= config.phone_confidence))
    persons, phones = [], []
    for row, class_id, confidence in zip(data[wanted], classes[wanted], confidences[wanted]):
        cx, cy, width, height = (float(value) for value in row[:4])
        if width <= 0 or height <= 0 or not 0 <= float(confidence) <= 1:
            continue
        x1 = (cx - width / 2 - transform.left) / transform.scale / transform.source_width
        x2 = (cx + width / 2 - transform.left) / transform.scale / transform.source_width
        y1 = (cy - height / 2 - transform.top) / transform.scale / transform.source_height
        y2 = (cy + height / 2 - transform.top) / transform.scale / transform.source_height
        box = Box(max(0., min(1., x1)), max(0., min(1., y1)),
                  max(0., min(1., x2)), max(0., min(1., y2)), float(confidence), int(class_id))
        if box.width <= 0 or box.height <= 0:
            continue
        if class_id == 0 and box.area >= config.person_min_area and box.height >= config.person_min_height:
            persons.append(box)
        elif class_id == 67 and box.area >= config.phone_min_area:
            phones.append(box)
    return _nms(persons, config.nms_iou), _nms(phones, config.nms_iou)


class YoloDetector:
    def __init__(self, config: VisionConfig, *, session: Any = None):
        self.config = config
        self._ort = None
        self._gpu_active = False
        if session is None:
            path = Path(config.yolo_model)
            if not path.is_file():
                raise FileNotFoundError(f"Local YOLO model missing: {path}. Prepare models before the offline session.")
            import onnxruntime as ort
            self._ort = ort
            providers = ["CPUExecutionProvider"]
            if config.prefer_gpu and "CUDAExecutionProvider" in ort.get_available_providers():
                providers.insert(0, "CUDAExecutionProvider")
            try:
                session = self._create_session(providers)
            except Exception:
                if providers == ["CPUExecutionProvider"]:
                    raise
                session = self._create_session(["CPUExecutionProvider"])
        self.session = session
        self._inspect_input()
        self.provider = self.session.get_providers()[0]
        self._gpu_active = self.provider != "CPUExecutionProvider"

    def _create_session(self, providers):
        options = self._ort.SessionOptions()
        options.intra_op_num_threads = self.config.cpu_threads
        options.inter_op_num_threads = 1
        options.graph_optimization_level = self._ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        return self._ort.InferenceSession(str(self.config.yolo_model), sess_options=options, providers=providers)

    def _inspect_input(self):
        inputs = self.session.get_inputs()
        if len(inputs) != 1 or len(inputs[0].shape) != 4:
            raise ValueError("YOLO model must have one NCHW image input")
        item = inputs[0]
        if item.type != "tensor(float)":
            raise ValueError("YOLO model must use float32 input; export with half=False")
        batch, channels, height, width = item.shape
        if isinstance(batch, int) and batch != 1:
            raise ValueError("YOLO model must support batch size one")
        if isinstance(channels, int) and channels != 3:
            raise ValueError("YOLO model must accept RGB input")
        self.input_name = item.name
        self.input_width = width if isinstance(width, int) and width > 0 else self.config.yolo_input_size
        self.input_height = height if isinstance(height, int) and height > 0 else self.config.yolo_input_size
        self.fixed_input = isinstance(width, int) and isinstance(height, int)

    def detect(self, frame) -> tuple[tuple[Box, ...], tuple[Box, ...]]:
        tensor, transform = preprocess(frame, self.input_width, self.input_height)
        try:
            outputs = self.session.run(None, {self.input_name: tensor})
        except Exception:
            if not self._gpu_active or self._ort is None:
                raise
            # A compatible provider may still fail at first execution; CPU is mandatory.
            self.session = self._create_session(["CPUExecutionProvider"])
            self.provider = "CPUExecutionProvider"
            self._gpu_active = False
            outputs = self.session.run(None, {self.input_name: tensor})
        if len(outputs) != 1:
            raise ValueError("Expected one raw YOLO COCO detection output")
        return decode(outputs[0], transform, self.config)

    def close(self) -> None:
        self.session = None
