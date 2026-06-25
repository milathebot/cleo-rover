"""On-Pi camera perception with graceful degradation.

The point of this module is to turn a captured camera frame into a structured
analysis (summary/labels/objects/hazards) that flows through the SAME path as
external vision (`/vision/analysis`) so that ``pip-brain`` finally sees fresh
``latest_vision`` instead of structurally ``null``.

Backends are imported lazily, exactly like the rest of the codebase treats
gpiozero/spidev:

* If the optional ``vision`` extra is installed (tflite-runtime + numpy) AND a
  model file is configured and present, a lightweight INT8 SSD-MobileNet detector
  runs (research pick: ~5-11 FPS on a Pi 4B, advisory-only).
* Otherwise (sim/dev host, or a Pi that hasn't installed the extra / has no
  model yet) it returns a low-confidence placeholder so events, the brain packet
  and advisory navigation all keep working.

Vision is ADVISORY ONLY. It can add a stop/scan constraint; it can never relax
the ultrasonic/cliff/bumper reflexes, which stay authoritative on the Pi.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

# Labels (COCO-ish) that should bias Pip toward caution if detected ahead.
HAZARD_LABELS = {"cat", "dog", "person", "cup", "bottle", "chair", "couch", "potted plant", "book", "cell phone"}
PET_LABELS = {"cat", "dog"}


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def vision_backends() -> dict[str, bool]:
    """Report which optional perception backends are importable on this host."""
    return {
        "tflite_runtime": _module_available("tflite_runtime"),
        "tensorflow": _module_available("tensorflow"),
        "picamera2": _module_available("picamera2"),
        "opencv": _module_available("cv2"),
        "numpy": _module_available("numpy"),
        "pillow": _module_available("PIL"),
    }


def _tflite_available() -> bool:
    backends = vision_backends()
    return (backends["tflite_runtime"] or backends["tensorflow"]) and backends["numpy"] and backends["pillow"]


def _hazards_from_labels(labels: list[str]) -> list[str]:
    lowered = {str(label).strip().lower() for label in labels}
    return sorted(lowered & HAZARD_LABELS)


def _placeholder_analysis(zone: str, image_path: str | Path | None, *, note: str | None = None) -> dict[str, Any]:
    return {
        "summary": "Scene captured; on-device detector unavailable (placeholder).",
        "labels": ["scene"],
        "objects": [],
        "confidence": 0.2,
        "zone": zone,
        "snapshot_path": str(image_path) if image_path else None,
        "source": "vision_local_placeholder",
        "clear_path": None,
        "hazards": [],
        "backends": vision_backends(),
        "note": note,
    }


def _load_labelmap(labelmap_path: str | Path | None) -> dict[int, str]:
    if not labelmap_path or not Path(labelmap_path).exists():
        return {}
    labels: dict[int, str] = {}
    for index, line in enumerate(Path(labelmap_path).read_text(encoding="utf-8").splitlines()):
        text = line.strip()
        if not text:
            continue
        # Support either "id name" or bare "name" per line.
        parts = text.split(maxsplit=1)
        if len(parts) == 2 and parts[0].isdigit():
            labels[int(parts[0])] = parts[1]
        else:
            labels[index] = text
    return labels


def _tflite_analyze(
    image_path: str | Path,
    *,
    zone: str,
    conf_threshold: float,
    model_path: str | Path,
    labelmap_path: str | Path | None,
) -> dict[str, Any]:  # pragma: no cover - requires tflite runtime + model on a Pi
    import numpy as np  # type: ignore
    from PIL import Image  # type: ignore

    try:
        from tflite_runtime.interpreter import Interpreter  # type: ignore
    except ImportError:
        from tensorflow.lite.python.interpreter import Interpreter  # type: ignore

    interpreter = Interpreter(model_path=str(model_path))
    interpreter.allocate_tensors()
    in_detail = interpreter.get_input_details()[0]
    _, in_h, in_w, _ = in_detail["shape"]
    img = Image.open(image_path).convert("RGB").resize((int(in_w), int(in_h)))
    arr = np.asarray(img)
    if in_detail["dtype"] == np.uint8:
        tensor = arr.astype(np.uint8)[None, ...]
    else:
        tensor = (arr.astype(np.float32) / 255.0)[None, ...]
    interpreter.set_tensor(in_detail["index"], tensor)
    interpreter.invoke()

    outputs = interpreter.get_output_details()
    # Standard SSD-MobileNet TFLite output order: boxes, classes, scores, count.
    boxes = interpreter.get_tensor(outputs[0]["index"])[0]
    classes = interpreter.get_tensor(outputs[1]["index"])[0]
    scores = interpreter.get_tensor(outputs[2]["index"])[0]
    labelmap = _load_labelmap(labelmap_path)

    objects: list[dict[str, Any]] = []
    for box, cls, score in zip(boxes, classes, scores):
        if float(score) < conf_threshold:
            continue
        label = labelmap.get(int(cls), f"class_{int(cls)}")
        ymin, xmin, ymax, xmax = [float(v) for v in box]
        cx = (xmin + xmax) / 2.0
        objects.append(
            {
                "label": label,
                "confidence": round(float(score), 3),
                "bbox_norm": [round(xmin, 3), round(ymin, 3), round(xmax, 3), round(ymax, 3)],
                "bearing_bucket": "left" if cx < 0.4 else "right" if cx > 0.6 else "center",
            }
        )

    labels = sorted({obj["label"] for obj in objects}) or ["scene"]
    center_objs = [o for o in objects if o["bearing_bucket"] == "center"]
    clear_path = len(center_objs) == 0
    top_conf = max((o["confidence"] for o in objects), default=0.25)
    summary = ("Open view ahead." if clear_path else "Something is in the path ahead.") + (
        f" Saw: {', '.join(labels)}." if objects else ""
    )
    return {
        "summary": summary,
        "labels": labels,
        "objects": objects,
        "confidence": round(float(top_conf), 3),
        "zone": zone,
        "snapshot_path": str(image_path),
        "source": "vision_local_tflite",
        "clear_path": clear_path,
        "hazards": _hazards_from_labels(labels),
    }


def analyze_frame(
    image_path: str | Path | None,
    *,
    zone: str = "unknown",
    conf_threshold: float = 0.45,
    model_path: str | Path | None = None,
    labelmap_path: str | Path | None = None,
) -> dict[str, Any]:
    """Analyze a captured frame. Always returns a vision-analysis-shaped dict.

    Falls back to a low-confidence placeholder when the detector, model, or image
    is unavailable, so the perception->brain pipeline never silently produces
    nothing.
    """
    if not image_path or not Path(image_path).exists():
        return _placeholder_analysis(zone, image_path, note="no image to analyze")
    if not (_tflite_available() and model_path and Path(model_path).exists()):
        return _placeholder_analysis(zone, image_path, note="tflite/model unavailable")
    try:
        return _tflite_analyze(
            image_path,
            zone=zone,
            conf_threshold=conf_threshold,
            model_path=model_path,
            labelmap_path=labelmap_path,
        )
    except Exception as exc:  # pragma: no cover - hardware/model dependent
        return _placeholder_analysis(zone, image_path, note=f"detector error: {exc!r}")
