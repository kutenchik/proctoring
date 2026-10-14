---
license: agpl-3.0
pipeline_tag: object-detection
tags:
- ultralytics
- tracking
- instance-segmentation
- image-classification
- pose-estimation
- obb
- object-detection
- yolo
- yolov8
library_name: ultralytics
model-index:
- name: ultralytics/yolo11
  results:
  - task:
      type: object-detection
    dataset:
      type: merve/coco
      name: coco
      split: validation
    metrics:
      - type: precision  # since mAP@0.5:0.95 is not available on hf.co/metrics
        value: 54.7
        name: mAP@0.5:0.95
---
---

[Ultralytics](https://www.ultralytics.com/) [YOLO11](https://github.com/ultralytics/ultralytics) is a cutting-edge, state-of-the-art (SOTA) model that builds upon the success of previous YOLO versions and introduces new features and improvements to further boost performance and flexibility. YOLO11 is designed to be fast, accurate, and easy to use, making it an excellent choice for a wide range of object detection and tracking, instance segmentation, image classification and pose estimation tasks.

This is an ONNX version of https://huggingface.co/Ultralytics/YOLO11 modified for the usage of [Transformers.js](https://huggingface.co/docs/transformers.js) JavaScript library.
