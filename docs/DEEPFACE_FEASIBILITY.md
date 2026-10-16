# DeepFace feasibility and pinned integration contract

Research date: 2026-10-15. This note records primary-source inspection and dependency resolution, not face accuracy or physical acceptance. No existing Python environment was changed by this investigation; no model weights, camera frames, or personal images were downloaded or processed by the researcher.

## Release and Windows dependency feasibility

Pin `deepface==0.0.102`: PyPI records its wheel upload at 2026-10-09 18:56:45 UTC, Python >=3.8, and wheel SHA-256 `d8840ea05c3bf33b35c3441d8f74fdef3ba58c2835ef22c5a0282c8403e7d152`. This release already has ONNX as a base dependency; TensorFlow and PyTorch are extras. Do not infer the installed API from older TensorFlow examples or unpinned master. [Official release metadata](https://pypi.org/pypi/deepface/0.0.102/json)

An all-binary Windows x64 / CPython 3.11 pip dry-run completed successfully (exit 0), using `--ignore-installed --only-binary=:all: --platform win_amd64 --python-version 3.11 --implementation cp --abi cp311 --dry-run`. Pip 23.2.1 required an unused temporary `--target` even in dry-run mode. It downloaded dependency wheels for resolution but installed nothing. The resulting temporary report is `%TEMP%/deepface-0102-win311-report.json`.

Relevant resolved versions: ONNX Runtime 1.31.0, NumPy 2.4.6, opencv-contrib-python-headless 5.0.0.93, pandas 3.0.6, retina-face 0.0.19; no TensorFlow or Torch. Other dependencies include requests, gdown, Pillow, Flask, flask-cors, fire, gunicorn, python-dotenv and tqdm. Wheel resolution is **not** an import, inference or performance test. Preserve the report and lock the full dependency graph before distributing an optional runtime. Use a separate environment: the headless OpenCV distribution and NumPy versions must not replace the existing student environment's dependencies.

Force `DEEPFACE_BACKEND_ENGINE=onnx` before the first DeepFace call/import in the isolated worker. Automatic selection prefers installed TensorFlow, then Torch, then ONNX, and caches that choice. [Pinned backend selection](https://github.com/serengil/deepface/blob/v0.0.102/deepface/commons/backend_utils.py)

## Recognition choices and model artifacts

Both supported candidates produce 512-dimensional embeddings. `Facenet512` takes 160x160 model inputs; `ArcFace` takes 112x112. The smaller downloaded Facenet512 graph makes it the initial CPU candidate, but download size does not establish latency, memory consumption or accuracy. [Pinned Facenet implementation](https://github.com/serengil/deepface/blob/v0.0.102/deepface/models/facial_recognition/onnx/Facenet.py), [ArcFace implementation](https://github.com/serengil/deepface/blob/v0.0.102/deepface/models/facial_recognition/onnx/ArcFace.py)

The pinned implementations use `https://github.com/serengil/deepface_models/releases/download/v1.0/<filename>` and an author-maintained Hugging Face backup. Metadata below was read from that author's repository; hashes are upstream LFS SHA-256 declarations, **not locally recomputed weight hashes**. Pin backup download URLs to `https://huggingface.co/serengil/deepface/resolve/d1783fe36379546024d548c77e23600a02ce1696/<filename>`, not mutable `main`. [Official model metadata](https://huggingface.co/api/models/serengil/deepface/tree/d1783fe36379546024d548c77e23600a02ce1696?expand=true)

| Artifact | Bytes | Declared SHA-256 |
| --- | ---: | --- |
| facenet512_weights.onnx | 93,956,456 | a7a4fbcc6af3175f5c4e91de0b92b4fa387e0e9f141efd59616337220363da33 |
| arcface_weights.onnx | 136,588,094 | a897e00dcf6f15e99f7218f8ed081550ebd38c7115c434772faa7c488eb6ad40 |
| 2.7_80x80_MiniFASNetV2.onnx | 1,746,407 | 2e0b0bdcdaf2ed0e8ceae7a8588a8b029c0f1bf2b15876eee942b68ce51bbb29 |
| 4_0_0_80x80_MiniFASNetV1SE.onnx | 1,745,918 | 1e2645be6e42759714f19ee23641366cf3d86cba5f169964880894a1fc188275 |

Upstream caches models under `<DEEPFACE_HOME>/.deepface/weights` (default home is the user's home). Its downloader trusts an existing filename and does **not** verify a content hash. Therefore provision approved files before the exam, recompute their hashes against an independently approved manifest, validate the exact package/runtime/model identities, and prohibit network retrieval at runtime. Missing/corrupt models must yield unavailable, never a fallback pass. [Cache location](https://github.com/serengil/deepface/blob/v0.0.102/deepface/commons/folder_utils.py), [Downloader](https://github.com/serengil/deepface/blob/v0.0.102/deepface/commons/weight_utils.py)

## Pinned API semantics

`DeepFace.extract_faces` accepts a BGR NumPy image and the options `detector_backend`, `enforce_detection`, `align`, `expand_percentage`, `grayscale`, `color_face`, `normalize_face`, `anti_spoofing`, and `max_faces`. For one image it returns face dictionaries. With `anti_spoofing=True`, each includes `is_real` and `antispoof_score`; otherwise these keys are absent. Require exactly one detected face, detection enforcement, validated output types and finite scores. Do not use `max_faces=1` to conceal a second face. [Pinned face extraction](https://github.com/serengil/deepface/blob/v0.0.102/deepface/modules/detection.py)

FasNet uses two MiniFASNet graphs with 80x80 crops at scales 2.7 and 4. It adds their three-class softmax outputs, chooses the winning class, treats label 1 as real, and reports half the summed score of **that winning class**. Thus `antispoof_score` is not always a real-person probability: a high score paired with `is_real=False` supports the spoof classification. Preserve the boolean and score together; low confidence is inconclusive rather than proof of liveness. [Pinned FasNet implementation](https://github.com/serengil/deepface/blob/v0.0.102/deepface/models/spoofing/onnx/FasNet.py)

`verification.find_threshold(model_name, distance_metric)` returns model-specific upstream defaults. Cosine thresholds are 0.30 for Facenet512 and 0.68 for ArcFace; matching uses `distance <= threshold`. For L2-normalized Euclidean they are 1.04 and 1.13 respectively. These are upstream defaults, not calibrated proctoring acceptance guarantees. Keep the model, normalization, alignment, detector and metric identical between enrollment and comparison. [Threshold table](https://github.com/serengil/deepface/blob/v0.0.102/deepface/config/threshold.py), [Verification implementation](https://github.com/serengil/deepface/blob/v0.0.102/deepface/modules/verification.py)

ONNX sessions prefer CUDA if available and otherwise CPU; for reproducible CPU measurements explicitly restrict the worker to the CPU provider. Generated arrays can exercise `represent(..., detector_backend='skip')` and direct FasNet analysis with a supplied rectangle for load/latency measurements. This skips face detection and is **not** a liveness or identity validation. Never use skip-detection results as an admission pass. [Pinned ONNX runtime helper](https://github.com/serengil/deepface/blob/v0.0.102/deepface/commons/onnx_utils.py)

## Licensing and rollout decision

DeepFace's wrapper is MIT. Its documentation explicitly says wrapped model licenses remain applicable. Facenet's referenced source is MIT; MiniFASNet's source is Apache-2.0. Retain upstream notices and record the precise weight provenance separately from wrapper licensing. [DeepFace license](https://github.com/serengil/deepface/blob/v0.0.102/LICENSE), [Facenet license](https://github.com/davidsandberg/facenet/blob/master/LICENSE.md), [MiniFASNet license](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing/blob/master/LICENSE)

ArcFace's linked Keras Insightface implementation has MIT code, but its README restricts training data and models trained on it to noncommercial research. A permissive code license is not evidence that the specific converted weight file is cleared for production. Keep ArcFace disabled for deployment until artifact-specific rights are established. [Author's licensing distinction](https://github.com/leondgarse/Keras_insightface#license)

Recommendation: optional isolated CPU worker, initially Facenet512 plus MiniFASNet, with a host-approved artifact manifest and explicit capability/readiness status. Do not add age, gender, emotion, race, celebrity search, external API calls or identity databases. Store only the minimum per-attempt reference needed for comparison, with consent and the existing retention rules. Treat spoof/mismatch outputs as review signals; repeated good-quality observations and bounded uncertainty handling are application requirements, not guarantees furnished by this library.

Remaining empirical work: actual isolated-runtime import and graph load, cold/warm latency, peak memory and worker termination tests; then separately authorized real-camera quality, demographic/lighting robustness and presentation-attack validation. This researcher performed no real-model inference or physical test. Any later synthetic benchmark must explicitly distinguish generated-array timing from recognition/liveness accuracy.


Implementation follow-up: isolated import/ONNX load, generated-array benchmarks and worker lifecycle checks were subsequently completed by the main task; see [implementation results](REMOTE_ACCESS_LIVENESS_IDENTITY.md). The complete OpenCV 5 extraction path additionally needs the official OpenCV 4.9.0 face/eye cascade XMLs, now explicitly prepared, hash-verified and loaded at readiness. These are not present in the OpenCV 5 wheel. Real-face accuracy remains unverified.
