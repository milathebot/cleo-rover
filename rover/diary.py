"""Pip's diary: a short, TRUTHFUL first-person narrative of its inner life.

Part of making Pip feel like a living being rather than a service: turn its real
state -- mood/energy, what it's been doing (recent behaviors/events), what it has
learned (semantic facts + known places), and how it feels about its body
(battery) -- into a few honest sentences. No invention: every line is grounded in
data Pip actually has. Pure + side-effect-free; the ``/life/diary`` endpoint feeds
it from the event log, the facts table, and the topo graph.
"""

from __future__ import annotations

from typing import Any

# Map raw arbiter behavior labels to first-person phrasing.
_BEHAVIOR_PHRASES = {
    "observe": "I kept a quiet watch over my space",
    "patrol": "I wandered a little, curious about what's around",
    "socialize": "someone came by and I said hello",
    "return_to_charger": "I felt low on energy and headed for my charger",
    "pursue_goal": "I worked on something I was asked to do",
    "rest": "I rested",
    "hold": "I paused because something was in my way",
}

_MOOD_PHRASES = {
    "calm": "calm and content",
    "curious": "curious about the world",
    "happy": "happy",
    "playful": "a bit playful",
    "excited": "excited",
    "alert": "alert and watchful",
    "sad": "a little down",
    "lonely": "lonely",
    "seeking": "restless, wanting to explore",
    "low_power": "tired and low",
    "proud": "quietly proud",
    "shy": "shy",
}


def _behavior_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ev in events:
        label = str(ev.get("label") or "")
        if label.startswith("arbiter:"):
            beh = label.split(":", 1)[1].split(":", 1)[0]
            counts[beh] = counts.get(beh, 0) + 1
    return counts


def compose_diary(
    *,
    feelings: dict[str, Any],
    recent_events: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    place_count: int = 0,
    battery_percent: float | None = None,
    charging: bool = False,
) -> dict[str, Any]:
    """Compose a short diary from Pip's real state. Returns {mood_line, lines, summary}."""
    mood = str(feelings.get("mood") or "calm")
    energy = feelings.get("energy")
    mood_word = _MOOD_PHRASES.get(mood, mood)
    energy_pct = f" (about {round(float(energy) * 100)}% energy)" if energy is not None else ""
    mood_line = f"Today I feel {mood_word}{energy_pct}."

    lines: list[str] = [mood_line]

    # What I did, most-frequent behavior first.
    counts = _behavior_counts(recent_events)
    for beh, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:3]:
        phrase = _BEHAVIOR_PHRASES.get(beh)
        if phrase:
            lines.append(phrase.capitalize() + ".")

    # What I've learned about my home.
    if place_count:
        lines.append(f"I've learned my way around {place_count} place{'s' if place_count != 1 else ''} so far.")
    top_facts = sorted(facts, key=lambda f: float(f.get("confidence", 0) or 0), reverse=True)[:2]
    for fact in top_facts:
        subj, obj = fact.get("subject"), fact.get("object")
        if subj and obj:
            detail = f" ({fact['detail']})" if fact.get("detail") else ""
            lines.append(f"I remember the {subj} is in the {obj}{detail}.")

    # How my body feels.
    if charging:
        lines.append("I'm charging now, getting my strength back.")
    elif battery_percent is not None and battery_percent <= 30:
        lines.append("I'm getting tired and should find my charger soon.")

    if len(lines) == 1:
        lines.append("It's been a quiet stretch; not much has happened yet.")

    return {"mood_line": mood_line, "lines": lines, "summary": " ".join(lines)}
