"""A topological place-graph for a robot with no reliable global pose.

With no encoders/IMU, a *metric* SLAM map smears and doubles within a few metres
of dead-reckoning drift. The robust model for this hardware is **topological**: a
graph whose nodes are *places* (recognised by a multi-modal fingerprint) and whose
edges are *transitions* (the action that took Pip from one place to the next).
Absolute coordinates never need to be accurate -- because Pip *relocalises at
every node*, open-loop drift between two recognisable places only has to be good
enough to get there, and never compounds across a whole route.

A place fingerprint fuses three cheap, independent cues (so one being fooled does
not cause a false match):

* **sonar signature** -- the panned range vector ``[r(theta0)..r(thetaN)]``; a
  corner/doorway has a characteristic profile.
* **visual descriptor** -- a normalised colour/intensity histogram of the scene
  (optional; empty when no camera).
* **IR context** -- a small bitmask of the floor-sensor state (thresholds, rugs).

Recognition requires **>= 2 of the 3** modalities to agree (voting), which is far
more robust than any single cue. This module is pure + in-memory and serialises
to/from a plain dict for SQLite-backed persistence. It is ADVISORY for navigation;
movement still flows through the Pi-local safety primitives.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field

SONAR_OUT_OF_RANGE_CM = 300.0


# --------------------------------------------------------------------------- #
# Pure similarity helpers
# --------------------------------------------------------------------------- #
def sonar_signature_match(cur: list[float | None], stored: list[float | None], *, tol: float = 0.15) -> float:
    """Fraction of beams that agree within ``tol`` relative range. 0..1.

    Beams that are out-of-range/None in either signature are ignored. Returns 0
    when fewer than 4 comparable beams exist (too little to trust).
    """
    pairs = []
    for a, b in zip(cur, stored):
        if a is None or b is None or a >= SONAR_OUT_OF_RANGE_CM or b >= SONAR_OUT_OF_RANGE_CM:
            continue
        pairs.append((float(a), float(b)))
    if len(pairs) < 4:
        return 0.0
    agree = sum(1 for a, b in pairs if abs(a - b) / max(b, 1e-3) < tol)
    return agree / len(pairs)


def hist_similarity(a: list[float], b: list[float]) -> float | None:
    """Cosine similarity of two equal-length descriptors, clamped to 0..1.

    Returns None if either descriptor is empty (no visual cue available).
    """
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0 or nb <= 0:
        return None
    return max(0.0, min(1.0, dot / (na * nb)))


@dataclass
class PlaceNode:
    id: str
    name: str
    sonar_sig: list[float | None] = field(default_factory=list)
    hist_desc: list[float] = field(default_factory=list)
    ir_context: int = 0
    visits: int = 1
    confidence: float = 0.5
    first_seen_at: float | None = None
    last_seen_at: float | None = None


@dataclass
class PlaceEdge:
    src: str
    dst: str
    action: str = "forward"
    heading_out: float = 0.0
    travel_time: float = 0.0
    traversals: int = 1


@dataclass(frozen=True)
class RecognitionResult:
    node_id: str | None
    score: float
    votes: dict[str, float]  # per-modality agreement for the best candidate
    reason: str


class TopoMap:
    """In-memory topological place graph. Serialise via :meth:`to_dict`."""

    def __init__(
        self,
        *,
        sonar_thresh: float = 0.6,
        hist_thresh: float = 0.8,
        min_votes: int = 2,
    ) -> None:
        self.nodes: dict[str, PlaceNode] = {}
        self.edges: list[PlaceEdge] = []
        self.sonar_thresh = sonar_thresh
        self.hist_thresh = hist_thresh
        self.min_votes = min_votes
        self._counter = 0

    # --- recognition --------------------------------------------------------
    def recognize(
        self, sonar_sig: list[float | None], hist_desc: list[float], ir_context: int = 0
    ) -> RecognitionResult:
        """Find the best matching place by >=2-of-3 modality voting."""
        best: RecognitionResult | None = None
        for node in self.nodes.values():
            sonar_score = sonar_signature_match(sonar_sig, node.sonar_sig)
            hist_score = hist_similarity(hist_desc, node.hist_desc)
            ir_match = 1.0 if (ir_context and node.ir_context and ir_context == node.ir_context) else 0.0
            votes = 0
            if sonar_score >= self.sonar_thresh:
                votes += 1
            if hist_score is not None and hist_score >= self.hist_thresh:
                votes += 1
            if ir_match >= 1.0:
                votes += 1
            if votes < self.min_votes:
                continue
            combined = sonar_score + (hist_score or 0.0) + ir_match
            detail = {"sonar": round(sonar_score, 3), "hist": round(hist_score, 3) if hist_score is not None else None, "ir": ir_match}
            if best is None or combined > best.score:
                best = RecognitionResult(node.id, round(combined, 3), detail, f"{votes}/3 modalities agree")
        return best or RecognitionResult(None, 0.0, {}, "no place matched >=2 modalities")

    # --- mutation -----------------------------------------------------------
    def _new_id(self) -> str:
        self._counter += 1
        return f"place-{self._counter}"

    def add_node(
        self,
        *,
        sonar_sig: list[float | None],
        hist_desc: list[float] | None = None,
        ir_context: int = 0,
        name: str | None = None,
        now: float | None = None,
    ) -> PlaceNode:
        nid = self._new_id()
        node = PlaceNode(
            id=nid,
            name=name or nid,
            sonar_sig=list(sonar_sig),
            hist_desc=list(hist_desc or []),
            ir_context=ir_context,
            visits=1,
            confidence=0.5,
            first_seen_at=now,
            last_seen_at=now,
        )
        self.nodes[nid] = node
        return node

    def reinforce(
        self,
        node_id: str,
        *,
        sonar_sig: list[float | None] | None = None,
        hist_desc: list[float] | None = None,
        now: float | None = None,
    ) -> PlaceNode:
        """Re-observe a known place: bump confidence (diminishing returns) + visits,
        and running-average the signatures so descriptors track slow change."""
        node = self.nodes[node_id]
        node.visits += 1
        node.confidence = round(min(1.0, node.confidence + 0.25 * (1.0 - node.confidence)), 3)
        node.last_seen_at = now
        if sonar_sig is not None and len(sonar_sig) == len(node.sonar_sig):
            node.sonar_sig = _avg_sig(node.sonar_sig, sonar_sig, node.visits)
        if hist_desc and len(hist_desc) == len(node.hist_desc):
            w = 1.0 / node.visits
            node.hist_desc = [(1 - w) * o + w * n for o, n in zip(node.hist_desc, hist_desc)]
        return node

    def add_edge(self, src: str, dst: str, *, action: str = "forward", heading_out: float = 0.0, travel_time: float = 0.0) -> PlaceEdge:
        for e in self.edges:
            if e.src == src and e.dst == dst and e.action == action:
                e.traversals += 1
                e.travel_time = (e.travel_time + travel_time) / 2.0
                return e
        edge = PlaceEdge(src=src, dst=dst, action=action, heading_out=heading_out, travel_time=travel_time)
        self.edges.append(edge)
        return edge

    def observe(
        self,
        *,
        sonar_sig: list[float | None],
        hist_desc: list[float] | None = None,
        ir_context: int = 0,
        last_node_id: str | None = None,
        action: str = "forward",
        heading_out: float = 0.0,
        travel_time: float = 0.0,
        now: float | None = None,
        name: str | None = None,
    ) -> dict:
        """Fingerprint the current place: recognise (merge + relocalise) or add a
        new node. Links an edge from ``last_node_id`` when one is supplied."""
        rec = self.recognize(sonar_sig, hist_desc or [], ir_context)
        if rec.node_id is not None:
            self.reinforce(rec.node_id, sonar_sig=sonar_sig, hist_desc=hist_desc, now=now)
            if last_node_id and last_node_id != rec.node_id:
                self.add_edge(last_node_id, rec.node_id, action=action, heading_out=heading_out, travel_time=travel_time)
            return {"event": "recognized", "node_id": rec.node_id, "relocalized": True, "recognition": _rec_dict(rec)}
        node = self.add_node(sonar_sig=sonar_sig, hist_desc=hist_desc, ir_context=ir_context, name=name, now=now)
        if last_node_id:
            self.add_edge(last_node_id, node.id, action=action, heading_out=heading_out, travel_time=travel_time)
        return {"event": "added", "node_id": node.id, "relocalized": False, "recognition": _rec_dict(rec)}

    def merge_duplicates(self, *, sonar_thresh: float = 0.8, hist_thresh: float = 0.9) -> int:
        """Offline pass: fuse near-identical nodes (counters slow descriptor drift
        spawning ghost rooms). Returns the number of merges performed."""
        ids = list(self.nodes)
        merged = 0
        removed: set[str] = set()
        for i, a_id in enumerate(ids):
            if a_id in removed:
                continue
            for b_id in ids[i + 1 :]:
                if b_id in removed:
                    continue
                a, b = self.nodes[a_id], self.nodes[b_id]
                s = sonar_signature_match(a.sonar_sig, b.sonar_sig)
                h = hist_similarity(a.hist_desc, b.hist_desc)
                if s >= sonar_thresh and (h is None or h >= hist_thresh):
                    self._absorb(a_id, b_id)
                    removed.add(b_id)
                    merged += 1
        return merged

    def _absorb(self, keep_id: str, drop_id: str) -> None:
        keep, drop = self.nodes[keep_id], self.nodes[drop_id]
        keep.visits += drop.visits
        keep.confidence = max(keep.confidence, drop.confidence)
        for e in self.edges:
            if e.src == drop_id:
                e.src = keep_id
            if e.dst == drop_id:
                e.dst = keep_id
        # Drop self-loops + exact duplicates created by the rewrite.
        seen: set[tuple] = set()
        deduped: list[PlaceEdge] = []
        for e in self.edges:
            if e.src == e.dst:
                continue
            key = (e.src, e.dst, e.action)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(e)
        self.edges = deduped
        del self.nodes[drop_id]

    # --- navigation ---------------------------------------------------------
    def node_by_name(self, name: str) -> PlaceNode | None:
        lowered = name.lower()
        for node in self.nodes.values():
            if node.name.lower() == lowered or lowered in node.name.lower():
                return node
        return None

    def plan(self, start_id: str, goal: str) -> dict:
        """Plan a route from ``start_id`` to a goal node id-or-name. Fewest-hops
        BFS over directed edges; returns node path + the actions to execute."""
        goal_node = self.nodes.get(goal) or self.node_by_name(goal)
        if start_id not in self.nodes or goal_node is None:
            return {"ok": False, "reason": "unknown start or goal", "path": [], "actions": []}
        goal_id = goal_node.id
        if start_id == goal_id:
            return {"ok": True, "path": [start_id], "actions": []}
        adj: dict[str, list[PlaceEdge]] = defaultdict(list)
        for e in self.edges:
            adj[e.src].append(e)
        queue: deque[list[str]] = deque([[start_id]])
        seen = {start_id}
        while queue:
            path = queue.popleft()
            node = path[-1]
            for e in adj[node]:
                if e.dst in seen:
                    continue
                new_path = path + [e.dst]
                if e.dst == goal_id:
                    return {"ok": True, "path": new_path, "actions": self._actions_for(new_path)}
                seen.add(e.dst)
                queue.append(new_path)
        return {"ok": False, "reason": "no route in graph", "path": [], "actions": []}

    def _actions_for(self, path: list[str]) -> list[dict]:
        out: list[dict] = []
        for a, b in zip(path, path[1:]):
            edge = next((e for e in self.edges if e.src == a and e.dst == b), None)
            if edge:
                out.append({"action": edge.action, "heading_out": edge.heading_out, "to": b})
        return out

    # --- (de)serialisation --------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "nodes": [asdict(n) for n in self.nodes.values()],
            "edges": [asdict(e) for e in self.edges],
            "counter": self._counter,
            "params": {"sonar_thresh": self.sonar_thresh, "hist_thresh": self.hist_thresh, "min_votes": self.min_votes},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TopoMap":
        params = data.get("params", {})
        m = cls(
            sonar_thresh=params.get("sonar_thresh", 0.6),
            hist_thresh=params.get("hist_thresh", 0.8),
            min_votes=params.get("min_votes", 2),
        )
        for nd in data.get("nodes", []):
            node = PlaceNode(**nd)
            m.nodes[node.id] = node
        m.edges = [PlaceEdge(**ed) for ed in data.get("edges", [])]
        m._counter = data.get("counter", len(m.nodes))
        return m

    def summary(self) -> dict:
        return {
            "places": len(self.nodes),
            "transitions": len(self.edges),
            "names": [n.name for n in self.nodes.values()][:20],
        }


def _avg_sig(old: list[float | None], new: list[float | None], visits: int) -> list[float | None]:
    w = 1.0 / max(1, visits)
    out: list[float | None] = []
    for o, n in zip(old, new):
        if o is None or n is None:
            out.append(n if o is None else o)
        else:
            out.append(round((1 - w) * o + w * n, 1))
    return out


def _rec_dict(rec: RecognitionResult) -> dict:
    return {"node_id": rec.node_id, "score": rec.score, "votes": rec.votes, "reason": rec.reason}
