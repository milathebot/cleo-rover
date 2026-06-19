from pathlib import Path

from PIL import Image

from rover.awareness import last_seen_summary, motion_score_between_images, prune_capture_dir, range_state_from_samples
from rover.models import SpatialMemoryItem


def test_range_state_from_samples():
    blocked = range_state_from_samples([24, 26, 25], stop_cm=30)
    assert blocked["state"] == "blocked"
    near = range_state_from_samples([45, 48, 50], stop_cm=30)
    assert near["state"] == "near"
    unknown = range_state_from_samples([None], stop_cm=30)
    assert unknown["state"] == "unknown"


def test_last_seen_summary_filters_semantic_items():
    items = [
        SpatialMemoryItem(id="cat", label="Mila", kind="vision_pet", zone="office", confidence=0.8, last_seen_at=10),
        SpatialMemoryItem(id="scan", label="scan", kind="range_scan", zone="office", confidence=0.8, last_seen_at=20),
    ]
    out = last_seen_summary(items)
    assert len(out) == 1
    assert out[0]["label"] == "Mila"


def test_prune_capture_dir_keeps_newest(tmp_path: Path):
    for i in range(3):
        p = tmp_path / f"{i}.jpg"
        p.write_bytes(b"x" * (i + 1))
    result = prune_capture_dir(tmp_path, keep=1)
    assert result["deleted"] == 2
    assert len(list(tmp_path.glob("*.jpg"))) == 1


def test_motion_score_between_images(tmp_path: Path):
    before = tmp_path / "before.jpg"
    after = tmp_path / "after.jpg"
    Image.new("RGB", (64, 64), "black").save(before)
    img = Image.new("RGB", (64, 64), "black")
    for x in range(20, 44):
        for y in range(20, 44):
            img.putpixel((x, y), (255, 255, 255))
    img.save(after)
    score = motion_score_between_images(before, after, size=(64, 64))
    assert score["motion_detected"] is True
