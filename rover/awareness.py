from __future__ import annotations

import os
import shutil
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat

from .models import SpatialMemoryItem

RANGE_BLOCKED_CM = 30.0
RANGE_NEAR_CM = 55.0
RANGE_CLEAR_CM = 120.0
SEMANTIC_KINDS = {"vision_person", "vision_pet", "vision_obstacle", "vision_area", "vision_object"}


def _read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except Exception:
        return None


def _cpu_temp_c() -> float | None:
    text = _read_text("/sys/class/thermal/thermal_zone0/temp")
    if not text:
        return None
    try:
        return round(float(text) / 1000.0, 1)
    except ValueError:
        return None


def cpu_temp_c() -> float | None:
    """Public CPU temperature (C) or None off-Pi. Used for thermal drive back-off."""
    return _cpu_temp_c()


def _load_average() -> list[float] | None:
    # os.getloadavg() is Unix-only (raises AttributeError on Windows dev hosts);
    # the Pi has it. Fail soft so the service/doctor work cross-platform.
    try:
        return [round(value, 2) for value in os.getloadavg()]
    except (OSError, AttributeError):
        return None


def _memory_info() -> dict[str, Any] | None:
    text = _read_text("/proc/meminfo")
    if not text:
        return None
    values: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            key = parts[0].rstrip(":")
            try:
                values[key] = int(parts[1])
            except ValueError:
                pass
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return None
    used = total - available
    return {
        "total_mb": round(total / 1024, 1),
        "available_mb": round(available / 1024, 1),
        "used_mb": round(used / 1024, 1),
        "used_percent": round(used / total * 100, 1),
    }


def _disk_info(path: str | Path) -> dict[str, Any]:
    usage = shutil.disk_usage(path)
    return {
        "path": str(path),
        "total_gb": round(usage.total / 1024**3, 2),
        "used_gb": round(usage.used / 1024**3, 2),
        "free_gb": round(usage.free / 1024**3, 2),
        "used_percent": round(usage.used / usage.total * 100, 1) if usage.total else None,
    }


def _command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def doctor_report(*, data_path: str | Path, capture_dir: str | Path, status: dict[str, Any], sensors: dict[str, Any]) -> dict[str, Any]:
    root = Path(data_path).expanduser().parent
    capture_path = Path(capture_dir).expanduser()
    warnings: list[str] = []
    cpu_temp = _cpu_temp_c()
    memory = _memory_info()
    disk = _disk_info(root if root.exists() else Path("."))
    if cpu_temp is not None and cpu_temp >= 75:
        warnings.append(f"cpu hot: {cpu_temp}C")
    if memory and memory["available_mb"] < 350:
        warnings.append(f"low memory: {memory['available_mb']}MB available")
    if disk.get("free_gb") is not None and disk["free_gb"] < 2:
        warnings.append(f"low disk: {disk['free_gb']}GB free")
    if status.get("motors_armed") and status.get("safety", {}).get("bench_safe_no_motors"):
        warnings.append("inconsistent safety: motors armed while bench_safe_no_motors=true")
    if sensors.get("errors"):
        warnings.append("sensor errors present")
    return {
        "ok": not warnings,
        "warnings": warnings,
        "system": {
            "cpu_temp_c": cpu_temp,
            "load_average": _load_average(),
            "memory": memory,
            "disk": disk,
            "pid": os.getpid(),
            "uptime_seconds": _process_uptime_seconds(),
        },
        "tools": {
            "rpicam_still": _command_exists("rpicam-still"),
            "libcamera_still": _command_exists("libcamera-still"),
            "python": shutil.which("python") or shutil.which("python3"),
        },
        "data": {
            "database": str(data_path),
            "database_bytes": Path(data_path).stat().st_size if Path(data_path).exists() else 0,
            "capture_dir": str(capture_path),
            "capture_count": len(list(capture_path.glob("*.jpg"))) if capture_path.exists() else 0,
        },
        "status": status,
        "sensor_ready": {
            "camera": bool(sensors.get("camera", {}).get("ready")),
            "rgb": bool(sensors.get("rgb", {}).get("ready")),
            "ultrasonic": bool(sensors.get("ultrasonic_ready")),
            "adc": bool(sensors.get("adc_ready")),
            "line_sensors": bool(sensors.get("line_sensors_ready")),
        },
    }


def _process_uptime_seconds() -> float | None:
    try:
        stat = Path(f"/proc/{os.getpid()}/stat").read_text().split()
        start_ticks = int(stat[21])
        clock_ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        return round(uptime - (start_ticks / clock_ticks), 1)
    except Exception:
        return None


def range_state_from_samples(samples: list[float | int | None], *, stop_cm: float) -> dict[str, Any]:
    clean = [float(sample) for sample in samples if sample is not None]
    if not clean:
        return {"state": "unknown", "median_cm": None, "samples": [], "stop_cm": stop_cm}
    median = round(statistics.median(clean), 1)
    if median < stop_cm or median < RANGE_BLOCKED_CM:
        state = "blocked"
    elif median < RANGE_NEAR_CM:
        state = "near"
    elif median < RANGE_CLEAR_CM:
        state = "clear"
    else:
        state = "open"
    return {"state": state, "median_cm": median, "samples": [round(v, 1) for v in clean], "stop_cm": stop_cm}


def last_seen_summary(items: list[SpatialMemoryItem], *, limit: int = 20) -> list[dict[str, Any]]:
    semantic = [item for item in items if item.kind in SEMANTIC_KINDS]
    semantic.sort(key=lambda item: item.last_seen_at or 0, reverse=True)
    out = []
    now = time.time()
    for item in semantic[:limit]:
        out.append({
            "id": item.id,
            "label": item.label,
            "kind": item.kind,
            "zone": item.zone,
            "bearing_deg": item.bearing_deg,
            "distance_m": item.distance_m,
            "confidence": item.confidence,
            "observations": item.observations,
            "last_seen_at": item.last_seen_at,
            "age_seconds": round(now - item.last_seen_at, 1) if item.last_seen_at else None,
            "snapshot_path": (item.payload.get("analysis") or {}).get("snapshot_path") if isinstance(item.payload, dict) else None,
        })
    return out


def prune_capture_dir(capture_dir: str | Path, *, keep: int = 500, dry_run: bool = False) -> dict[str, Any]:
    path = Path(capture_dir).expanduser()
    if not path.exists():
        return {"ok": True, "capture_dir": str(path), "deleted": 0, "kept": 0, "bytes_freed": 0}
    files = sorted(path.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
    delete = files[max(0, keep):]
    bytes_freed = sum(p.stat().st_size for p in delete if p.exists())
    if not dry_run:
        for file in delete:
            try:
                file.unlink()
            except FileNotFoundError:
                pass
    return {"ok": True, "capture_dir": str(path), "deleted": len(delete), "kept": min(len(files), keep), "bytes_freed": bytes_freed, "dry_run": dry_run}


def motion_score_between_images(before: str | Path, after: str | Path, *, size: tuple[int, int] = (320, 240)) -> dict[str, Any]:
    a = Image.open(before).convert("L").resize(size)
    b = Image.open(after).convert("L").resize(size)
    diff = ImageChops.difference(a, b)
    stat = ImageStat.Stat(diff)
    mean_delta = float(stat.mean[0])
    thresholded = Image.eval(diff, lambda px: 255 if px > 25 else 0)
    bbox = thresholded.getbbox()
    return {"ok": True, "mean_delta": round(mean_delta, 3), "motion_detected": mean_delta >= 6.0 or bbox is not None, "bbox": bbox, "size": list(size)}


def capture_motion_pair(capture_command: list[str], output_dir: str | Path, *, delay_seconds: float = 0.6) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    first = out / f"motion-a-{int(time.time())}.jpg"
    second = out / f"motion-b-{int(time.time())}.jpg"
    for path in (first, second):
        cmd = [part.format(output=str(path)) for part in capture_command]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
        if result.returncode != 0 or not path.exists():
            return {"ok": False, "error": "capture failed", "path": str(path), "returncode": result.returncode, "stderr": result.stderr[-500:]}
        time.sleep(delay_seconds)
    score = motion_score_between_images(first, second)
    return {"ok": True, "first": str(first), "second": str(second), "motion": score}
