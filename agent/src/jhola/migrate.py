"""One-off data migration: single-household key layout -> per-household partitions.

Before tenancy the demo household's state lived in the collections orders, mandate, txns, audit,
purchases, sessions and rules, with counters "audit" and "orders". They are COPIED (never moved or
deleted) into hh#demo-gupta#<collection>, so the old items stay readable and a rollback is possible.
The copy is idempotent: existing target documents are never overwritten, counters only move up.

    AWS_PROFILE=... uv run python -m jhola.migrate jhola-state            # migrate
    AWS_PROFILE=... uv run python -m jhola.migrate jhola-state --dry-run  # only count
"""

from __future__ import annotations

import sys

from .domain import DEMO_HOUSEHOLD_ID
from .household import Directory, demo_phones_from_env
from .store import Repository, ScopedRepository

LEGACY_COLLECTIONS = ("orders", "mandate", "txns", "audit", "purchases", "sessions", "rules")


def migrate(repo: Repository, household_id: str = DEMO_HOUSEHOLD_ID, dry_run: bool = False,
            demo_phones: set[str] | None = None) -> dict:
    scoped = ScopedRepository(repo, household_id)
    report: dict = {}
    for c in LEGACY_COLLECTIONS:
        copied = skipped = 0
        for key in repo.keys(c):
            doc = repo.get(c, key)
            if doc is None:
                continue
            if dry_run:
                copied += scoped.get(c, key) is None
            elif scoped.put_new(c, key, doc):
                copied += 1
            else:
                skipped += 1
        report[c] = {"copied": copied, "already_there": skipped}
    # Counters: never below the old counter or anything already stored, so ids are never reused.
    old = {name: (repo.get("counters", name) or {}).get("n", 0) for name in ("audit", "orders")}
    seqs = [e.get("seq", 0) for e in scoped.list("audit")] if not dry_run else []
    nums = [int(k.rsplit("-", 1)[1]) for k in (scoped.keys("orders") if not dry_run else [])
            if k.rsplit("-", 1)[-1].isdigit()]
    targets = {"audit": max([old["audit"], *seqs]), "orders": max([old["orders"], *nums])}
    if not dry_run:
        for name, n in targets.items():
            if n:
                scoped.raise_seq(name, n)
        Directory(repo).ensure_demo(demo_phones if demo_phones is not None else demo_phones_from_env())
    report["counters"] = targets
    return report


def main(argv: list[str]) -> int:
    import json

    from .store import DynamoDBRepository

    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2
    print(json.dumps(migrate(DynamoDBRepository(argv[0]), dry_run="--dry-run" in argv), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
