# Offline model manifest

The app loads two local files and never contacts a model host. Prepare using
`python scripts/fetch_models.py`, or copy exact files before the demo. The script
pins sources and verifies SHA-256. Binaries are excluded from version control.

| File | Source | SHA-256 |
|---|---|---|
| `yolo11n.onnx` | [webnn/yolo11n pinned export](https://huggingface.co/webnn/yolo11n/tree/9c5acfdd74aaff2d0f47c51b878506361039a51f) | `7d8fd1717d9d5bbab6986cd134afb620649c7a394303d55b1e09fc00804cc5c1` |
| `face_landmarker.task` | [Google Face Landmarker float16 v1](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task) | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` |

YOLO is a community ONNX export of Ultralytics YOLO11n, not an export produced
by this project. The source card identifies AGPL-3.0; consult the source terms
and [Ultralytics documentation](https://docs.ultralytics.com/models/yolo11/) before
redistribution. See also the [official Face Landmarker guide](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker).

Compatible replacements: float32 NCHW YOLO11n detection ONNX trained on COCO,
one raw output `[1,84,N]` or `[1,N,84]`, `nms=False`, batch size one. Person is
class 0; cell phone is class 67. End-to-end NMS, segmentation/pose, quantized and
custom class-order exports are unsupported. Dynamic spatial dimensions use
`yolo_input_size`; fixed dimensions are read from the model and shown in metrics.
Both model paths are configurable.
