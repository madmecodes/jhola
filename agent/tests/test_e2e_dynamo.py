"""End to end against a REAL DynamoDB table, with WhatsApp sending stubbed and a scripted model.

    JHOLA_E2E_TABLE=jhola-state AWS_PROFILE=... AWS_DEFAULT_REGION=ap-south-1 uv run pytest tests/test_e2e_dynamo.py -s

Uses throwaway phone numbers, creates two households, and deletes everything it created afterwards.
It never touches the demo household or any real member.
"""

import os
import random

import pytest
from helpers import World, body, button_ids, order, staple_between, to

from jhola.config import Clock
from jhola.store import DynamoDBRepository

TABLE = os.environ.get("JHOLA_E2E_TABLE")
pytestmark = pytest.mark.skipif(not TABLE, reason="set JHOLA_E2E_TABLE to run against a real DynamoDB table")


def fake_phone():
    return "+9170000" + f"{random.randint(0, 99999):05d}"  # 70000xxxxx is not an allocated mobile series


def test_two_households_end_to_end_on_dynamodb():
    repo = DynamoDBRepository(TABLE)
    w = World(repo=repo, clock=Clock())
    admin, didi, other = fake_phone(), fake_phone(), fake_phone()
    a = b = None
    try:
        # a new phone onboards
        assert "1/3" in body(w.say(admin, "hi")[0])
        w.say(admin, "E2E Priya, E2E test home")
        w.tap(admin, "onb:default")
        done = w.say(admin, "1000")
        assert "E2E test home" in body(done[0])
        a = w.ch.dir.lookup(admin)["household_id"]

        # a second, unrelated household is created in parallel
        b = w.onboard(other, name="E2E Rahul")

        # the admin adds a member with a limit (Yes / No first)
        out = w.say(admin, "Add Sunita didi, groceries only, 500 a day",
                    __import__("helpers").propose("propose_add_member", {
                        "name": "Sunita didi", "phone": didi, "role": "house_help", "daily_limit_inr": 500,
                        "categories": ["groceries"]}))
        assert w.ch.dir.lookup(didi) is None
        w.tap(admin, button_ids(out[0])[0])
        assert w.ch.dir.lookup(didi) == {"household_id": a, "member_id": "sunita", "demo": False}
        assert "Namaste Sunita didi" in body(w.say(didi, "hi")[0])

        # within the limit: auto-pay. Over the limit: approval goes to the admin's phone. Admin approves.
        item = staple_between(250, 500)
        out = w.say(didi, "order", order(item["id"]))
        assert "SIMULATED" in body(to(out, didi)[0]) and to(out, admin) == []
        out = w.say(didi, "order again", order(item["id"]))
        [ask] = to(out, admin)
        assert "daily limit" in body(ask)
        out = w.tap(admin, button_ids(ask)[0])
        assert "Approved" in body(to(out, admin)[0]) and to(out, didi)
        A = w.app(a)
        assert [o["status"] for o in A.repo.list("orders")] == ["paid", "paid"]
        assert A.month_spent() == 2 * item["price_inr"]
        assert {o["order_id"][-4:] for o in A.repo.list("orders")} == {"0001", "0002"}

        # the other household sees none of it
        B = w.app(b)
        for c in ("orders", "txns", "purchases", "rules", "prefs", "pending_actions"):
            assert B.repo.list(c) == [], c
        assert [m.id for m in B.hh.members] == ["e2e"] and B.month_spent() == 0
        assert [e["event"] for e in B.audit.events()] == ["household_created"]
        assert "no such order" in body(w.tap(other, "approve:" + A.repo.list("orders")[1]["order_id"])[0])
        print(f"\nE2E ok on {TABLE}: households {a} and {b}, {len(A.audit.events())} audit events in A")
    finally:
        for hid in (a, b):
            if hid:
                w.ch.dir.delete_household(hid)
        for p in (admin, didi, other):
            for c in ("phones", "onboarding", "wa_last_inbound"):
                repo.delete(c, p)
    assert w.ch.dir.lookup(admin) is None and repo.list(f"hh#{a}#orders") == []
