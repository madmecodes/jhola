"""Append-only structured audit log."""

from __future__ import annotations

from typing import Any

from .config import Clock
from .store import Repository

class AuditLog:
    def __init__(self, repo: Repository, clock: Clock) -> None:
        self.repo = repo
        self.clock = clock
        self._n = len(repo.list("audit"))

    def log(self, event: str, order_id: str | None = None, actor: str | None = None, **data: Any) -> dict:
        self._n += 1
        n = self._n
        ev = {
            "seq": n,
            "ts": self.clock.now().isoformat(),
            "event": event,
            "order_id": order_id,
            "actor": actor,
            "data": data,
        }
        self.repo.put("audit", f"{n:08d}", ev)
        return ev

    def events(self, order_id: str | None = None) -> list[dict]:
        evs = sorted(self.repo.list("audit"), key=lambda e: e["seq"])
        return [e for e in evs if order_id is None or e["order_id"] == order_id]
