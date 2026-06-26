"""Layered long-term memory for the LLM mind — the #1 'aliveness' lever.

The mind otherwise gets fresh context every call and forgets across sessions. This
distills Pip's durable knowledge — the places it knows, the consolidated facts it
has learned, the people/pets it has met, and a short rolling journal of recent days
— into a compact block + a first-person narrative that rides along in the brain
packet. Pure + side-effect-free; the service supplies the persisted inputs (topo
places, the semantic-facts table, spatial memory, and a daily-diary journal kept in
the KV store).
"""

from __future__ import annotations

from typing import Any

PERSON_WORDS = {"person", "human", "noot", "wife"}
PET_WORDS = {"cat", "kitten", "kitty", "dog", "pet"}


def known_people_and_pets(spatial_items: list[dict[str, Any]]) -> list[str]:
    """Distinct person/pet labels Pip has seen (from spatial memory)."""
    seen: list[str] = []
    for item in spatial_items:
        label = str(item.get("label") or "").strip().lower()
        kind = str(item.get("kind") or "").lower()
        if not label:
            continue
        is_being = "person" in kind or "pet" in kind or any(w in label for w in PERSON_WORDS | PET_WORDS)
        if is_being and label not in seen:
            seen.append(label)
    return seen[:8]


def _fact_phrase(fact: dict[str, Any]) -> str | None:
    subj, pred, obj = fact.get("subject"), fact.get("predicate"), fact.get("object")
    if not subj or not obj:
        return None
    pred = str(pred or "is in").replace("_", " ")
    detail = f" ({fact['detail']})" if fact.get("detail") else ""
    return f"the {subj} {pred} the {obj}{detail}"


def compose_longterm_memory(
    *,
    facts: list[dict[str, Any]] | None = None,
    places: list[str] | None = None,
    spatial_items: list[dict[str, Any]] | None = None,
    journal: list[dict[str, Any]] | None = None,
    cat_sightings_recent: int = 0,
    max_facts: int = 5,
    max_days: int = 5,
) -> dict[str, Any]:
    """Build {known_places, facts, people, recent_days, narrative}. Everything is
    grounded in real persisted state — nothing invented."""
    facts = facts or []
    places = [p for p in (places or []) if p]
    spatial_items = spatial_items or []
    journal = journal or []

    top_facts = sorted(facts, key=lambda f: float(f.get("confidence", 0) or 0), reverse=True)[:max_facts]
    fact_phrases = [p for p in (_fact_phrase(f) for f in top_facts) if p]
    people = known_people_and_pets(spatial_items)
    recent_days = journal[-max_days:]

    parts: list[str] = []
    if places:
        shown = ", ".join(places[:6])
        parts.append(f"I know {len(places)} place{'s' if len(places) != 1 else ''} in my home ({shown}).")
    if fact_phrases:
        parts.append("I've learned that " + "; ".join(fact_phrases) + ".")
    if people:
        parts.append("I've met: " + ", ".join(people) + ".")
    if cat_sightings_recent:
        parts.append(f"I've seen a cat {cat_sightings_recent} time{'s' if cat_sightings_recent != 1 else ''} lately.")
    if recent_days:
        last = recent_days[-1]
        if last.get("summary"):
            parts.append("Recently: " + str(last["summary"]))

    return {
        "known_places": places[:12],
        "facts": fact_phrases,
        "people": people,
        "recent_days": recent_days,
        "cat_sightings_recent": cat_sightings_recent,
        "narrative": " ".join(parts) if parts else "I'm still getting to know my home.",
    }
