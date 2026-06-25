"""Execute a topological route -- traverse the place-graph to a goal (e.g. the
charger) and relocalize at every node so open-loop drift never compounds.

Pip can already *orient* toward a remembered landmark; this lets it actually
*travel* a multi-hop route ("office -> hall -> kitchen -> dock"). The key idea
(why a topo map suits a no-odometry robot): between two recognisable places the
dead-reckoning only has to be good enough to arrive, because at each node Pip
re-fingerprints and **resets** its position. If it can't recognise the expected
next place after a few tries, it gives up and asks for help instead of driving
blind.

This module is the PURE core: turn an edge action into bounded motions, and run
the advance/miss/abort bookkeeping. The async task in ``service.py`` does the
actual driving (rotate + forward) and calls ``topo.observe`` to relocalise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Edge action -> in-place turn (deg, +left). "forward" implies no pre-turn.
TURN_ACTIONS: dict[str, float] = {"turn_left": 90.0, "turn_right": -90.0, "turn_around": 180.0}


def edge_motions(action: str, heading_out: float = 0.0, *, segment_cm: float = 40.0, max_turn_deg: float = 90.0) -> list[tuple[str, float]]:
    """Bounded motion primitives to traverse one edge: an optional rotate, then a
    forward segment. Returns a list of ("rotate"|"forward", value)."""
    motions: list[tuple[str, float]] = []
    if action in TURN_ACTIONS:
        motions.append(("rotate", TURN_ACTIONS[action]))
    elif abs(heading_out) > 8.0:
        motions.append(("rotate", max(-max_turn_deg, min(max_turn_deg, float(heading_out)))))
    motions.append(("forward", float(segment_cm)))
    return motions


def rotation_chunks(deg: float, *, max_step: float = 45.0) -> list[float]:
    """Split a turn into <=max_step bounded pulses (rotate_step caps at ~45deg, so a
    90/180deg edge must be issued in chunks or it is silently truncated)."""
    out: list[float] = []
    remaining = float(deg)
    while abs(remaining) >= 1.0:
        step = max(-max_step, min(max_step, remaining))
        out.append(step)
        remaining -= step
    return out


@dataclass
class ReturnState:
    """Bookkeeping for a multi-hop return: where we are on the path, misses, status."""

    path: list[str]
    actions: list[dict] = field(default_factory=list)
    idx: int = 0  # index of the node we are currently AT, within path
    misses: int = 0
    max_misses: int = 3
    done: bool = False
    aborted: bool = False

    def __post_init__(self) -> None:
        # Already at the goal (single-node route): nothing to traverse, so we're
        # done -- don't drive off and abort against a None "expected next" (review).
        if len(self.path) <= 1:
            self.done = True

    @property
    def expected_next(self) -> str | None:
        return self.path[self.idx + 1] if self.idx + 1 < len(self.path) else None

    @property
    def current_action(self) -> dict | None:
        # actions[i] takes you from path[i] -> path[i+1].
        return self.actions[self.idx] if self.idx < len(self.actions) else None

    def on_observed(self, observed_id: str | None) -> str:
        """Relocalisation result after attempting the current edge.

        - observed == expected next place -> advance (and maybe finish).
        - otherwise -> a miss; abort after ``max_misses`` so Pip asks for help.
        """
        expected = self.expected_next
        if expected is not None and observed_id == expected:
            self.idx += 1
            self.misses = 0
            if self.idx >= len(self.path) - 1:
                self.done = True
            return "advanced"
        self.misses += 1
        if self.misses >= self.max_misses:
            self.aborted = True
            return "aborted"
        return "retry"

    def status(self) -> dict:
        return {
            "at_node": self.path[self.idx] if self.idx < len(self.path) else None,
            "expected_next": self.expected_next,
            "progress": f"{self.idx}/{max(1, len(self.path) - 1)}",
            "misses": self.misses,
            "done": self.done,
            "aborted": self.aborted,
        }


def plan_return(topo, start_id: str | None, goal: str) -> dict:
    """Plan a route to ``goal`` (node id or name) from ``start_id``. Graceful on
    unknown start/goal or no route (so the executor asks for help, not crashes)."""
    if not start_id:
        return {"ok": False, "reason": "no current place; run /topo/observe first", "path": [], "actions": []}
    return topo.plan(start_id, goal)
