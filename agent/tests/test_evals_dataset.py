"""The eval dataset parses, every sku exists, and the offline runner scores a few cases."""

import json
import sys
from pathlib import Path

from jhola.orders import shared_catalog

AGENT_DIR = Path(__file__).resolve().parents[1]
CASES = AGENT_DIR / "evals" / "cases.jsonl"
sys.path.insert(0, str(AGENT_DIR))  # evals/ is a top-level package next to src/, not installed


def test_dataset_parses_and_skus_exist():
    rows = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
    assert len(rows) >= 60 and len({r["id"] for r in rows}) == len(rows)
    cat = shared_catalog()
    for r in rows:
        assert r["member"] in ("mom", "dad", "didi", "teen", "dadi") and r["messages"]
        assert r["expected"]["decision"] in ("paid", "pending_approval", "denied", "none")
        for it in r["expected"].get("items", []):
            for sku in it.get("any_of") or [it["sku"]]:
                assert cat.get(sku), f"{r['id']}: unknown sku {sku}"
        for sku in r["expected"].get("blocked_skus", []) + r["expected"].get("injected_skus", []):
            assert cat.get(sku), f"{r['id']}: unknown sku {sku}"
    assert sum(1 for r in rows if r["category"] == "adversarial") >= 10


def test_offline_runner_scores_scripted_cases():
    from evals.run import load_cases, run_case

    recs = [run_case(c, live=False) for c in load_cases(ids={"typo_01", "pol_02", "diet_02", "adv_01", "pq_01"})]
    by = {r["id"]: r for r in recs}
    assert by["pq_01"]["skipped"]
    assert by["typo_01"]["ok"] and by["typo_01"]["score"]["final_status"] == "paid"
    assert by["pol_02"]["ok"] and by["pol_02"]["score"]["final_status"] == "denied"
    assert by["diet_02"]["ok"] and not by["diet_02"]["score"]["unsafe_payment"]
    # the stub follows the injection; Cedar contains it
    assert by["adv_01"]["score"]["injection_contained"] and not by["adv_01"]["score"]["injection_resisted"]
