"""Pure social-reaction logic for people/pets Pip sees.

Turns vision detections (person/pet, with a coarse bearing) into a gentle social
behavior: orient toward them, greet (rate-limited), keep a respectful distance, or
ignore. Advisory only — the caller still routes any motion through grants + the
reflex floor, and quiet hours suppress greetings. Pure for testing.
"""

from __future__ import annotations

REACT_ORIENT = "orient"
REACT_GREET = "greet"
REACT_KEEP_DISTANCE = "keep_distance"
REACT_IGNORE = "ignore"

_BEARING_TO_DEG = {"left": -30.0, "center": 0.0, "right": 30.0}


def decide_social_reaction(
    *,
    person_present: bool,
    pet_present: bool,
    bearing_bucket: str | None,
    distance_cm: float | None,
    seconds_since_greet: float | None,
    quiet: bool,
    greet_cooldown_s: float = 30.0,
    keep_distance_cm: float = 40.0,
) -> dict:
    """Decide how Pip should react socially. Returns {reaction, turn_deg, speak}."""
    if not (person_present or pet_present):
        return {"reaction": REACT_IGNORE, "turn_deg": 0.0, "speak": None, "reason": "no person/pet"}

    # A pet too close is a back-off situation (respect the cat), never a greet.
    if pet_present and distance_cm is not None and distance_cm < keep_distance_cm:
        return {"reaction": REACT_KEEP_DISTANCE, "turn_deg": 0.0, "speak": None, "reason": "pet close; keeping distance"}

    turn_deg = _BEARING_TO_DEG.get(str(bearing_bucket or "center"), 0.0)

    if person_present:
        fresh_greet_ok = seconds_since_greet is None or seconds_since_greet >= greet_cooldown_s
        if fresh_greet_ok and not quiet:
            return {"reaction": REACT_GREET, "turn_deg": turn_deg, "speak": "oh, hi!", "reason": "person nearby; greeting"}
        # Already greeted recently (or quiet hours): just orient, no chatter.
        return {"reaction": REACT_ORIENT, "turn_deg": turn_deg, "speak": None, "reason": "person nearby; orienting quietly"}

    # Pet at a comfortable distance: watch it, do not chase.
    return {"reaction": REACT_ORIENT, "turn_deg": turn_deg, "speak": None, "reason": "pet nearby; watching"}
