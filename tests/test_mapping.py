from rover.mapping import classify_label, map_summary, observation_items, semantic_events_from_analysis
from rover.models import RoverEventKind, SpatialMemoryItem


def test_observation_items_classify_people_pets_and_obstacles():
    analysis = {
        "summary": "Noot, Mila, and a chair are visible.",
        "labels": ["person", "cat", "chair"],
        "objects": [{"label": "cat", "position": "left", "confidence": 0.8}],
        "confidence": 0.75,
    }
    items = observation_items(zone="office", bearing_deg=10, distance_cm=120, analysis=analysis)
    assert {item.kind for item in items} >= {"vision_person", "vision_pet", "vision_obstacle"}
    assert classify_label("Mila") == "pet"


def test_semantic_events_from_analysis():
    events = semantic_events_from_analysis(
        {"labels": ["person", "cat", "chair"], "confidence": 0.8},
        distance_cm=80,
        bearing_deg=0,
    )
    assert {event.kind for event in events} == {RoverEventKind.motion, RoverEventKind.obstacle}
    assert any(event.label == "pet seen" for event in events)


def test_map_summary_groups_memory():
    items = [
        SpatialMemoryItem(id="a", label="chair", kind="vision_obstacle", zone="office", distance_m=0.8, confidence=0.8),
        SpatialMemoryItem(id="b", label="Mila", kind="vision_pet", zone="office", distance_m=1.2, confidence=0.9),
    ]
    summary = map_summary(items)
    assert summary["total_items"] == 2
    assert summary["kinds"]["vision_pet"] == 1
    assert summary["zones"]["office"]["vision_obstacle"] == 1
    assert summary["nearest"]["label"] == "chair"
