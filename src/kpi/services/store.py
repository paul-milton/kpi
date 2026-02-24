"""Snapshot store using TinyDB for arbitrary date comparisons."""
from __future__ import annotations
from pathlib import Path
from typing import Any
import structlog
from tinydb import Query, TinyDB
from kpi.domain.models import Snapshot
logger = structlog.get_logger()

class SnapshotStore:
    def __init__(self, cfg: dict[str, Any]) -> None:
        p = Path(cfg.get("archive", {}).get("db_path", "data/kpi.json"))
        p.parent.mkdir(parents=True, exist_ok=True)
        self._db = TinyDB(str(p), indent=2)
        self._tbl = self._db.table("snapshots")

    def save(self, snap: Snapshot) -> int:
        q = Query()
        self._tbl.remove(q.snapshot_date == snap.snapshot_date)
        return self._tbl.insert(snap.model_dump())

    def load_by_date(self, dt: str) -> Snapshot | None:
        r = self._tbl.search(Query().snapshot_date == dt)
        return Snapshot(**r[0]) if r else None

    def load_by_sprint(self, sprint_number: int) -> Snapshot | None:
        r = self._tbl.search(Query().sprint_number == sprint_number)
        if not r: return None
        r.sort(key=lambda d: d["snapshot_date"], reverse=True)
        return Snapshot(**r[0])

    def load_previous_sprint(self, current: int) -> Snapshot | None:
        r = self._tbl.search(Query().sprint_number < current)
        if not r: return None
        r.sort(key=lambda d: d["snapshot_date"], reverse=True)
        return Snapshot(**r[0])

    def load_latest_before(self, dt: str) -> Snapshot | None:
        r = self._tbl.search(Query().snapshot_date < dt)
        if not r: return None
        r.sort(key=lambda d: d["snapshot_date"], reverse=True)
        return Snapshot(**r[0])

    def compare(self, a: str, b: str) -> tuple[Snapshot | None, Snapshot | None]:
        return self.load_by_date(a), self.load_by_date(b)

    def load_all(self) -> list[Snapshot]:
        docs = self._tbl.all()
        docs.sort(key=lambda d: d.get("snapshot_date", ""))
        return [Snapshot(**d) for d in docs]
