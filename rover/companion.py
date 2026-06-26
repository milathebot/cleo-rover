"""Pip's household-companion personality content + small pure helpers.

Keeps the *words* and the deterministic logic for the "living being around the
house" behaviors in one tested, side-effect-free place: stair carry-requests,
proactive idle musings, cat reactions, time-aware greetings, the cat-sightings
report, daily digest text, and the hazard-zone check. The service wires these to
speech/RGB/Telegram; the LLM mind can override the wording when it's online.
"""

from __future__ import annotations

from typing import Any

# --- stairs / edges: ask to be carried ---------------------------------------
CARRY_LINES = [
    "Uh oh — stairs. I can't go down by myself. Can someone carry me?",
    "Whoa, an edge! I need a lift to get down, please.",
    "I found the stairs again. A little help getting down?",
    "Eep — a drop ahead. Could a human carry me down?",
]

# --- proactive idle musings (deterministic fallback when the mind is offline) -
PROACTIVE_GENERIC = [
    "It's quiet up here… I wonder where everyone is.",
    "Just keeping watch over the office.",
    "Hmm, I wonder what's happening downstairs.",
    "I should explore a little more later.",
    "All calm on the second floor.",
]
PROACTIVE_PET = "I think one of the cats wandered by — I'll keep an eye out."
PROACTIVE_PERSON = "Oh good, I'm not alone up here."

# --- cat mode -----------------------------------------------------------------
CAT_LINES = [
    "Oh! A kitty! Hello, friend.",
    "A cat! Don't worry, I'll keep my distance.",
    "Here, kitty kitty… I mean, beep boop.",
    "One of the fuzzy overlords has appeared.",
]


def _pick(options: list[str], n: int) -> str:
    return options[int(n) % len(options)] if options else ""


def carry_request_line(n: int = 0) -> str:
    return _pick(CARRY_LINES, n)


def cat_reaction_line(n: int = 0) -> str:
    return _pick(CAT_LINES, n)


def proactive_line(n: int = 0, *, person: bool = False, pet: bool = False, place: str | None = None) -> str:
    if pet:
        return PROACTIVE_PET
    if person:
        return PROACTIVE_PERSON
    if place and place not in {"unmapped", "unknown", None}:
        return f"I'm hanging around the {place}, keeping watch."
    return _pick(PROACTIVE_GENERIC, n)


def greeting_line(hour: int, name: str | None = None) -> str:
    """Time-aware greeting. hour is 0-23 local."""
    if 5 <= hour < 12:
        base = "Good morning!"
    elif 12 <= hour < 17:
        base = "Good afternoon!"
    elif 17 <= hour < 22:
        base = "Good evening!"
    else:
        base = "You're up late!"
    who = f" {name}" if name else ""
    return f"{base}{who}"


def compose_cat_report(sightings: list[dict[str, Any]]) -> str:
    """sightings: newest-first list of {zone, bearing, age_s}. Plain-English answer
    to 'where are the cats?'."""
    if not sightings:
        return "I haven't spotted any cats recently."
    latest = sightings[0]
    zone = latest.get("zone") or "somewhere nearby"
    age = latest.get("age_s")
    when = _humanize_age(age) if age is not None else "a little while ago"
    extra = f" I've seen a cat {len(sightings)} times recently." if len(sightings) > 1 else ""
    return f"I last saw a cat near the {zone} {when}.{extra}"


def _humanize_age(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"about {round(seconds / 60)} minutes ago"
    if seconds < 86400:
        return f"about {round(seconds / 3600)} hours ago"
    return "a while ago"


def compose_digest(diary: dict[str, Any], *, cat_sightings: int = 0, places: int = 0, battery_percent: float | None = None) -> str:
    """A friendly end-of-day summary for the owner's phone, built on the real diary."""
    lines = ["🤖 Pip's day:"]
    summary = diary.get("summary") or diary.get("mood_line") or "It was a quiet day."
    lines.append(summary)
    if cat_sightings:
        lines.append(f"🐱 Cat sightings: {cat_sightings}.")
    if places:
        lines.append(f"🗺️ Places I know: {places}.")
    if battery_percent is not None:
        lines.append(f"🔋 Battery: {round(float(battery_percent))}%.")
    return "\n".join(lines)


def is_hazard_place(node: str | None, hazard_zones: list[str] | set[str] | None) -> bool:
    """True if the current place is a marked no-go (e.g. the top of the stairs)."""
    if not node or not hazard_zones:
        return False
    node_l = str(node).lower()
    return any(node_l == str(z).lower() for z in hazard_zones)
