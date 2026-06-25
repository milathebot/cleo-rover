"""Memory consolidation: raw episodic observations -> durable semantic facts.

Pip writes lots of cheap episodic observations (saw a cat here, a charger there).
On idle / while charging, this module distills them into a small, self-cleaning
set of *semantic facts* ("the charger is located_in the office"), mirroring how
both robot long-term-memory and agent-memory systems work:

* **Promotion** -- an observation seen >= ``promote_n`` times at the same place
  graduates from episodic to a durable fact.
* **Reinforcement** -- re-observing a fact bumps its confidence (diminishing
  returns) and resets its decay clock.
* **Decay** -- facts lose confidence with age (half-life), so a world that
  changed (someone moved the charger) is gracefully forgotten.
* **Pruning** -- facts below a confidence floor are dropped, and raw episodes are
  discarded once consolidated, keeping storage bounded.

Pure + side-effect-free (lists in, lists out) so it is fully unit-testable; the
service feeds it episodes from the event log and persists the returned facts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

WEEK_S = 7 * 24 * 3600.0


@dataclass(frozen=True)
class ConsolidationConfig:
    half_life_s: float = WEEK_S  # confidence halves after this long unobserved
    promote_n: int = 3  # episodes at one place before it becomes a fact
    prune_conf: float = 0.15  # facts below this are dropped
    reinforce_gain: float = 0.25  # diminishing-returns confidence bump on re-observe
    episode_max_age_s: float = 2 * 24 * 3600.0  # raw episodes older than this are discarded
    predicate: str = "located_in"


@dataclass
class Fact:
    subject: str
    predicate: str
    object: str  # the place/zone
    detail: str = ""
    confidence: float = 0.5
    observations: int = 1
    first_seen_at: float | None = None
    last_seen_at: float | None = None

    def key(self) -> tuple[str, str, str]:
        return (self.subject.lower(), self.predicate, self.object.lower())


def decay(confidence: float, age_seconds: float | None, *, half_life_s: float = WEEK_S) -> float:
    if age_seconds is None or age_seconds <= 0:
        return round(float(confidence), 3)
    return round(float(confidence) * (0.5 ** (age_seconds / max(1.0, half_life_s))), 3)


def reinforce(confidence: float, *, gain: float = 0.25) -> float:
    return round(min(1.0, confidence + gain * (1.0 - confidence)), 3)


def _episode_zone(ep: dict[str, Any]) -> str | None:
    return ep.get("zone") or ep.get("object") or ep.get("place") or ep.get("node_id")


def _episode_label(ep: dict[str, Any]) -> str | None:
    return ep.get("label") or ep.get("subject")


def consolidate(
    episodes: list[dict[str, Any]],
    facts: list[Fact],
    *,
    now: float,
    cfg: ConsolidationConfig | None = None,
) -> dict[str, Any]:
    """Run one consolidation pass.

    ``episodes`` are dicts with at least ``label`` + a place (``zone``/``node_id``)
    and optionally ``confidence``/``timestamp``/``detail``. Returns the updated
    fact list plus counters and the episodes worth keeping.
    """
    cfg = cfg or ConsolidationConfig()
    by_key: dict[tuple[str, str, str], Fact] = {f.key(): f for f in facts}

    # 1) Group recent episodes by (label, place) and promote/reinforce.
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for ep in episodes:
        label, zone = _episode_label(ep), _episode_zone(ep)
        if not label or not zone:
            continue
        groups.setdefault((label, zone), []).append(ep)

    promoted = reinforced = 0
    for (label, zone), eps in groups.items():
        key = (label.lower(), cfg.predicate, zone.lower())
        confs = [float(e.get("confidence", 0.5) or 0.5) for e in eps]
        mean_conf = sum(confs) / len(confs)
        # An episode may stand for several observations (a spatial-memory item with
        # observations=N) via an optional "count" field; default 1 per episode.
        count = sum(int(e.get("count", 1)) for e in eps)
        detail = _summarize_detail(eps)
        fact = by_key.get(key)
        if fact is None:
            if count >= cfg.promote_n:
                by_key[key] = Fact(
                    subject=label, predicate=cfg.predicate, object=zone, detail=detail,
                    confidence=round(mean_conf, 3), observations=count, first_seen_at=now, last_seen_at=now,
                )
                promoted += 1
        else:
            fact.confidence = reinforce(fact.confidence, gain=cfg.reinforce_gain)
            fact.observations += count
            fact.last_seen_at = now
            fact.detail = detail or fact.detail
            reinforced += 1

    # 2) Decay everything by age, then prune the dead facts.
    out_facts: list[Fact] = []
    pruned = 0
    for fact in by_key.values():
        age = (now - fact.last_seen_at) if fact.last_seen_at else None
        fact.confidence = decay(fact.confidence, age, half_life_s=cfg.half_life_s)
        if fact.confidence < cfg.prune_conf:
            pruned += 1
            continue
        out_facts.append(fact)

    out_facts.sort(key=lambda f: f.confidence, reverse=True)

    # 3) Keep only recent raw episodes (older ones are now consolidated).
    kept_episodes = [e for e in episodes if (now - float(e.get("timestamp", now))) <= cfg.episode_max_age_s]

    return {
        "facts": out_facts,
        "promoted": promoted,
        "reinforced": reinforced,
        "pruned": pruned,
        "kept_episodes": kept_episodes,
        "fact_count": len(out_facts),
    }


def _summarize_detail(eps: list[dict[str, Any]]) -> str:
    """Coarse spatial detail from an episode group (e.g. dominant bearing side)."""
    bearings = [float(e["bearing_deg"]) for e in eps if e.get("bearing_deg") is not None]
    details = [str(e["detail"]) for e in eps if e.get("detail")]
    if details:
        return details[-1][:120]
    if bearings:
        avg = sum(bearings) / len(bearings)
        side = "left" if avg < -10 else "right" if avg > 10 else "ahead"
        return f"typically {side} (~{avg:+.0f}deg)"
    return ""


def facts_to_dicts(facts: list[Fact]) -> list[dict[str, Any]]:
    return [asdict(f) for f in facts]


def facts_from_dicts(rows: list[dict[str, Any]]) -> list[Fact]:
    allowed = {"subject", "predicate", "object", "detail", "confidence", "observations", "first_seen_at", "last_seen_at"}
    return [Fact(**{k: v for k, v in row.items() if k in allowed}) for row in rows]
