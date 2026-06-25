from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .models import AutonomyState, RoverEvent, SpatialMemoryItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp REAL NOT NULL,
  kind TEXT NOT NULL,
  source TEXT NOT NULL,
  value REAL,
  label TEXT,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
CREATE TABLE IF NOT EXISTS behavior_cooldowns (
  behavior TEXT PRIMARY KEY,
  last_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS spatial_memory (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  kind TEXT NOT NULL,
  zone TEXT,
  bearing_deg REAL,
  distance_m REAL,
  confidence REAL NOT NULL,
  notes TEXT,
  first_seen_at REAL NOT NULL,
  last_seen_at REAL NOT NULL,
  observations INTEGER NOT NULL,
  payload_json TEXT NOT NULL
);
"""


class RoverStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init(self) -> None:
        with self.connect() as con:
            con.executescript(SCHEMA)

    def save_json(self, key: str, value: Any) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO kv(key,value,updated_at) VALUES(?,?,?)",
                (key, json.dumps(value), time.time()),
            )

    def load_json(self, key: str) -> Any | None:
        with self.connect() as con:
            row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def save_state(self, state: AutonomyState) -> None:
        self.save_json("autonomy_state", state.model_dump(mode="json"))

    def load_state(self) -> AutonomyState | None:
        data = self.load_json("autonomy_state")
        return AutonomyState.model_validate(data) if data else None

    def save_cooldowns(self, cooldowns: dict[str, float]) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM behavior_cooldowns")
            con.executemany(
                "INSERT INTO behavior_cooldowns(behavior,last_at) VALUES(?,?)",
                sorted(cooldowns.items()),
            )

    def load_cooldowns(self) -> dict[str, float]:
        with self.connect() as con:
            rows = con.execute("SELECT behavior,last_at FROM behavior_cooldowns").fetchall()
        return {row["behavior"]: float(row["last_at"]) for row in rows}

    def add_event(self, event: RoverEvent) -> RoverEvent:
        if event.timestamp is None:
            event = event.model_copy(update={"timestamp": time.time()})
        with self.connect() as con:
            con.execute(
                "INSERT INTO events(timestamp,kind,source,value,label,payload_json) VALUES(?,?,?,?,?,?)",
                (event.timestamp, event.kind.value, event.source, event.value, event.label, json.dumps(event.payload)),
            )
        return event

    def recent_events(self, limit: int = 25, since: float | None = None, kind: str | None = None) -> list[RoverEvent]:
        sql = "SELECT * FROM events"
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)
        if kind is not None:
            # Kind-filtered lookup lets the brain find the latest vision_analysis
            # even when hundreds of per-angle scan events flood the recent window.
            clauses.append("kind = ?")
            params.append(kind)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self.connect() as con:
            rows = con.execute(sql, params).fetchall()
        return [
            RoverEvent(kind=row["kind"], source=row["source"], value=row["value"], label=row["label"], payload=json.loads(row["payload_json"]), timestamp=row["timestamp"])
            for row in rows
        ]

    def upsert_spatial(self, item: SpatialMemoryItem) -> SpatialMemoryItem:
        now = time.time()
        item = item.model_copy(update={
            "first_seen_at": item.first_seen_at or now,
            "last_seen_at": item.last_seen_at or now,
            "observations": max(1, item.observations),
        })
        with self.connect() as con:
            old = con.execute("SELECT observations,first_seen_at FROM spatial_memory WHERE id=?", (item.id,)).fetchone()
            if old:
                item = item.model_copy(update={"first_seen_at": old["first_seen_at"], "observations": int(old["observations"]) + 1, "last_seen_at": now})
            con.execute(
                """INSERT OR REPLACE INTO spatial_memory
                (id,label,kind,zone,bearing_deg,distance_m,confidence,notes,first_seen_at,last_seen_at,observations,payload_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item.id, item.label, item.kind, item.zone, item.bearing_deg, item.distance_m, item.confidence, item.notes,
                 item.first_seen_at, item.last_seen_at, item.observations, json.dumps(item.payload)),
            )
        return item

    def list_spatial(self, limit: int = 100) -> list[SpatialMemoryItem]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM spatial_memory ORDER BY last_seen_at DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
        return [SpatialMemoryItem(
            id=row["id"], label=row["label"], kind=row["kind"], zone=row["zone"], bearing_deg=row["bearing_deg"], distance_m=row["distance_m"],
            confidence=row["confidence"], notes=row["notes"], first_seen_at=row["first_seen_at"], last_seen_at=row["last_seen_at"], observations=row["observations"], payload=json.loads(row["payload_json"]),
        ) for row in rows]

    def prune_events(self, *, keep_days: int = 30, dry_run: bool = False) -> dict[str, Any]:
        cutoff = time.time() - max(1, keep_days) * 86400
        with self.connect() as con:
            count = int(con.execute("SELECT COUNT(*) FROM events WHERE timestamp < ?", (cutoff,)).fetchone()[0])
            if not dry_run:
                con.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
                con.execute("VACUUM")
        return {"ok": True, "deleted_events": count, "keep_days": keep_days, "dry_run": dry_run}
