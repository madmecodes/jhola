"""Console API tenancy (household_id, GET /api/households) and the data migration."""

import pytest
from helpers import World, order, staple_between

from jhola.api import ApiError, ConsoleApi
from jhola.api_handler import dispatch
from jhola.config import DEMO_NOW, Clock
from jhola.domain import DEMO_HOUSEHOLD_ID
from jhola.migrate import migrate
from jhola.orders import Jhola
from jhola.store import InMemoryRepository

KEY = {"x-jhola-demo-key": "k"}
PRIYA, SUNITA = "+919811100001", "+919811100002"


def key_check(headers):
    if headers.get("x-jhola-demo-key") != "k":
        raise ApiError(401, "missing or wrong x-jhola-demo-key")


def call(api, method, path, body=None, query=None, headers=None):
    return dispatch(api, method, path, query or {}, headers or {}, body or {}, "1.2.3.4", None, key_check)


@pytest.fixture
def world():
    w = World()
    w.hid = w.onboard(PRIYA)
    w.add_member(PRIYA, name="Sunita didi", phone=SUNITA, role="house_help")
    w.item = staple_between(100, 400)
    w.say(PRIYA, "order", order(w.item["id"]))
    w.api = ConsoleApi(w.repo, w.clock, model_factory=w.scripts, llm=w.llm)
    return w


def test_households_listing_is_key_guarded_and_masks_phones(world):
    with pytest.raises(ApiError) as e:
        call(world.api, "GET", "/api/households")
    assert e.value.status == 401
    hs = call(world.api, "GET", "/api/households", headers=KEY)["households"]
    assert [h["household_id"] for h in hs] == [DEMO_HOUSEHOLD_ID, world.hid] or \
        {h["household_id"] for h in hs} == {DEMO_HOUSEHOLD_ID, world.hid}
    mine = next(h for h in hs if h["household_id"] == world.hid)
    assert mine["member_count"] == 2 and mine["admins"] == ["+91******0001"] and not mine["demo"]
    assert PRIYA not in str(hs) and SUNITA not in str(hs)
    demo = next(h for h in hs if h["household_id"] == DEMO_HOUSEHOLD_ID)
    assert demo["demo"] and demo["member_count"] == 5 and demo["admins"] == ["+91******0001"]


def test_default_household_is_the_demo_and_others_need_the_key(world):
    assert call(world.api, "GET", "/api/household")["household"]["household_id"] == DEMO_HOUSEHOLD_ID
    assert call(world.api, "GET", "/api/orders")["orders"] == []  # the demo never sees Priya's order
    q = {"household_id": world.hid}
    for path in ("/api/household", "/api/orders", "/api/audit", "/api/approvals"):
        with pytest.raises(ApiError) as e:
            call(world.api, "GET", path, query=q)
        assert e.value.status == 401
    hh = call(world.api, "GET", "/api/household", query=q, headers=KEY)
    assert hh["household"]["name"] == "Sharma home" and hh["mandate"]["used_inr"] == world.item["price_inr"]
    assert [m["phone_masked"] for m in hh["members"]] == ["+91******0001", "+91******0002"]
    assert "Rs 1000" in next(r for r in hh["rules"] if r["id"] == "approval-above-threshold")["title_en"]
    [o] = call(world.api, "GET", "/api/orders", query=q, headers=KEY)["orders"]
    assert o["member_name"] == "Priya" and o["status"] == "paid"
    assert PRIYA not in str(call(world.api, "GET", "/api/audit", query=q, headers=KEY))
    with pytest.raises(ApiError) as e:
        call(world.api, "GET", "/api/orders", query={"household_id": "hh-doesnotexist"}, headers=KEY)
    assert e.value.status == 404
    with pytest.raises(ApiError) as e:
        call(world.api, "POST", "/api/chat", body={"member": "mom", "text": "x", "household_id": world.hid},
             headers=KEY)
    assert e.value.status == 400  # mom is not a member of this household


def test_web_chat_in_another_household_with_key(world):
    world.scripts.queue.append(order(world.item["id"]))
    out = call(world.api, "POST", "/api/chat", headers=KEY,
               body={"member": "priya", "text": "again", "household_id": world.hid})
    assert out["order"]["status"] == "paid" and out["order"]["channel"] == "web"
    assert len(world.app(world.hid).repo.list("orders")) == 2 and world.app(DEMO_HOUSEHOLD_ID).repo.list("orders") == []


def test_migration_copies_legacy_demo_data_and_keeps_the_old_keys():
    repo = InMemoryRepository()
    repo.put("orders", "JH-20260920-0010", {"order_id": "JH-20260920-0010", "member_id": "didi", "status": "paid",
                                           "lines": [], "created_at": "2026-09-20T10:00:00+05:30"})
    repo.put("mandate", "MNDT-GUPTA-0001", {"mandate_id": "MNDT-GUPTA-0001", "payer_vpa": "x@simbank",
                                            "monthly_cap_inr": 5000, "month": "2026-09", "month_spent_inr": 2300,
                                            "status": "ACTIVE"})
    repo.put("audit", "00000222", {"seq": 222, "event": "reply_sent", "order_id": None, "data": {}})
    repo.put("rules", "abc", {"id": "abc", "title": "t", "cedar": "", "active": False})
    repo.put("counters", "audit", {"n": 300})
    repo.put("counters", "orders", {"n": 10})
    owner = "+916300000009"
    report = migrate(repo, demo_phones={owner})
    assert report["orders"] == {"copied": 1, "already_there": 0} and report["counters"] == {"audit": 300, "orders": 10}
    assert migrate(repo, demo_phones={owner})["orders"] == {"copied": 0, "already_there": 1}  # idempotent
    assert repo.get("orders", "JH-20260920-0010") and repo.get("mandate", "MNDT-GUPTA-0001")  # old keys stay

    app = Jhola(repo, Clock(DEMO_NOW))
    assert app.month_spent() == 2300 and app.get_order("JH-20260920-0010")["status"] == "paid"
    assert app.audit.log("after_migration")["seq"] == 301  # never reuses an audit sequence
    assert app.build_cart(app.hh.member("didi"), [])["order_id"].endswith("-0011")
    assert repo.get("phones", owner) == {"household_id": DEMO_HOUSEHOLD_ID, "member_id": "mom", "demo": True}
