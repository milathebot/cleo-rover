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
import math
from dataclasses import dataclass
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


def optical_flow_available() -> bool:
    """Sparse optical flow needs OpenCV + numpy (the `vision` extra on a Pi)."""
    b = vision_backends()
    return b["opencv"] and b["numpy"]


# --------------------------------------------------------------------------- #
# Sparse optical flow: a cheap "am I actually moving?" / stall / yaw / looming
# cue from the camera. The DECISION logic below is pure (plain lists of point
# pairs) so it is fully unit-testable on a dev host; the OpenCV Lucas-Kanade
# capture path is hardware-only. Flow is ADVISORY: it can confirm a stall (so Pip
# stops trusting open-loop "I moved"), add a looming stop, and hint yaw -- it
# never relaxes a reflex.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FlowConfig:
    move_thresh_px: float = 1.2  # median flow above this => moving (CALIBRATE on bench)
    min_tracks: int = 8  # below this, flow is "unknown", not "stalled"
    stall_hysteresis: int = 3  # consecutive stalled frames before a confirmed stall
    ring_inner_px: float = 40.0  # divergence annulus (skip noisy focus-of-expansion)
    ring_outer_px: float = 130.0
    yaw_deadband_px: float = 0.8  # |mean dx| below this => not turning


@dataclass(frozen=True)
class FlowState:
    moving: bool | None  # None => too few tracks to tell
    stalled: bool  # commanded forward but image static (this frame)
    median_flow_px: float
    yaw_sign: int  # -1 right, 0 straight, +1 left (scene moves opposite the turn)
    yaw_rate_proxy: float  # mean horizontal flow (uncalibrated)
    ttc_frames: float | None  # crude time-to-collision from flow divergence
    n_tracks: int
    note: str


def flow_motion_state(
    prev_pts: list[tuple[float, float]],
    cur_pts: list[tuple[float, float]],
    *,
    cmd_linear: float = 0.0,
    img_w: int = 320,
    img_h: int = 240,
    cfg: FlowConfig | None = None,
) -> FlowState:
    """Reduce matched feature pairs to {moving?, stalled?, yaw, looming TTC}.

    ``prev_pts``/``cur_pts`` are matched (x, y) feature locations in the previous
    and current frame (same length). Pure: no OpenCV/numpy needed.
    """
    cfg = cfg or FlowConfig()
    n = min(len(prev_pts), len(cur_pts))
    if n < cfg.min_tracks:
        return FlowState(
            moving=None, stalled=False, median_flow_px=0.0, yaw_sign=0, yaw_rate_proxy=0.0,
            ttc_frames=None, n_tracks=n, note="too few tracks; motion unknown",
        )

    flows = [(cur_pts[i][0] - prev_pts[i][0], cur_pts[i][1] - prev_pts[i][1]) for i in range(n)]
    mags = sorted(math.hypot(dx, dy) for dx, dy in flows)
    median = mags[len(mags) // 2]
    mean_dx = sum(dx for dx, _ in flows) / n

    moving = median > cfg.move_thresh_px
    stalled = bool(cmd_linear > 0 and not moving)

    # Yaw: a left (CCW) turn makes the scene shift RIGHT (mean_dx > 0).
    if abs(mean_dx) <= cfg.yaw_deadband_px:
        yaw_sign = 0
    else:
        yaw_sign = 1 if mean_dx > 0 else -1  # scene-right (dx>0) => turned left (+1)

    # Looming: during forward translation the flow field diverges from the image
    # centre (focus of expansion). TTC ~ 1 / divergence, measured over an annulus
    # (the centre is too noisy). Only meaningful moving forward + roughly straight.
    ttc = None
    if moving and cmd_linear > 0 and yaw_sign == 0:
        cx, cy = img_w / 2.0, img_h / 2.0
        divs: list[float] = []
        for (px, py), (dx, dy) in zip(prev_pts, flows):
            rx, ry = px - cx, py - cy
            rn = math.hypot(rx, ry)
            if not (cfg.ring_inner_px < rn < cfg.ring_outer_px):
                continue
            radial = (dx * rx + dy * ry) / rn  # outward component
            if radial > 0:
                divs.append(radial / rn)
        if len(divs) >= 4:
            divs.sort()
            med_div = divs[len(divs) // 2]
            ttc = round(1.0 / med_div, 2) if med_div > 1e-3 else None

    note = "stalled (commanded but static)" if stalled else ("moving" if moving else "static")
    return FlowState(
        moving=moving, stalled=stalled, median_flow_px=round(median, 2), yaw_sign=yaw_sign,
        yaw_rate_proxy=round(mean_dx, 2), ttc_frames=ttc, n_tracks=n, note=note,
    )


class StallConfirmer:
    """Hysteresis wrapper: only declare a confirmed stall after N consecutive
    stalled frames, so a single noisy frame cannot trip a false stall."""

    def __init__(self, cfg: FlowConfig | None = None) -> None:
        self.cfg = cfg or FlowConfig()
        self._run = 0

    def update(self, state: FlowState) -> bool:
        if state.stalled:
            self._run += 1
        else:
            self._run = 0
        return self._run >= self.cfg.stall_hysteresis

    @property
    def streak(self) -> int:
        return self._run


def capture_flow_state(  # pragma: no cover - needs OpenCV + a live camera
    picam,
    prev_gray,
    *,
    cmd_linear: float = 0.0,
    cfg: FlowConfig | None = None,
    max_corners: int = 80,
):
    """Grab a lores grayscale frame, run sparse Lucas-Kanade vs ``prev_gray``, and
    return ``(FlowState, new_gray)``. Returns ``(None, prev_gray)`` if OpenCV is
    unavailable or there is no previous frame yet. Hardware-only path.
    """
    if not optical_flow_available():
        return None, prev_gray
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    yuv = picam.capture_array("lores")
    h = yuv.shape[0] * 2 // 3
    gray = yuv[:h, : yuv.shape[1]].copy()
    if prev_gray is None:
        return None, gray
    feat = dict(maxCorners=max_corners, qualityLevel=0.2, minDistance=10, blockSize=7)
    lk = dict(winSize=(15, 15), maxLevel=2, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03))
    p0 = cv2.goodFeaturesToTrack(prev_gray, mask=None, **feat)
    if p0 is None or len(p0) < (cfg or FlowConfig()).min_tracks:
        return None, gray
    p1, st, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, p0, None, **lk)
    good = st.flatten() == 1
    prev_list = [tuple(map(float, pt)) for pt in p0[good].reshape(-1, 2)]
    cur_list = [tuple(map(float, pt)) for pt in p1[good].reshape(-1, 2)]
    state = flow_motion_state(prev_list, cur_list, cmd_linear=cmd_linear, img_w=gray.shape[1], img_h=gray.shape[0], cfg=cfg)
    return state, gray


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
