"""Console API: routes, demo-key guard, rate limit, custom Cedar rules, red team, refill job."""

import base64

import pytest

from jhola import scenarios as sc
from jhola.api import ApiError, ConsoleApi
from jhola.api_handler import RateLimiter, dispatch
from jhola.config import DEMO_NOW, Clock
from jhola.parchi import render_parchi, transcription
from jhola.store import InMemoryRepository
from jhola.stub_model import ScriptedModel
from jhola.vision import FixtureVisionReader

KEY = "test-demo-key"


def key_check(headers):
    if headers.get("x-jhola-demo-key") != KEY:
        raise ApiError(401, "missing or wrong x-jhola-demo-key")


class Scripts:
    """model_factory that hands out a scripted model per call (the next script in the queue)."""

    def __init__(self):
        self.queue = []

    def __call__(self):
        return ScriptedModel(self.queue.pop(0))


@pytest.fixture
def api():
    scripts = Scripts()
    fixtures = FixtureVisionReader()
    a = ConsoleApi(InMemoryRepository(), Clock(DEMO_NOW), model_factory=scripts, vision=fixtures,
                   llm=fake_llm, sender=lambda to, text, buttons: ["mid-1"])
    a.scripts, a.fixtures = scripts, fixtures
    return a


def call(api, method, path, body=None, query=None, headers=None, limiter=None, ip="1.2.3.4"):
    return dispatch(api, method, path, query or {}, headers or {}, body or {}, ip, limiter, key_check)


DRAFT = """<title>No snacks above Rs 100 for Aarav</title>
<cedar>
@reason("Teens cannot buy a snack line above Rs 100.")
@hinglish("Aarav Rs 100 se mehenga snack nahi le sakta.")
forbid (principal, action == Action::"purchase_item", resource)
when { principal.role == "teen" && resource.category == "snacks" && context.line_total_inr > 100 };
</cedar>
<explanation_en>Aarav cannot buy snacks costing more than Rs 100 per line.</explanation_en>
<explanation_hinglish>Aarav Rs 100 se upar ke snacks nahi le sakta.</explanation_hinglish>
<tests>
[{"case": "Aarav buys chips for Rs 150", "member": "teen", "action": "purchase_item",
  "product": {"category": "snacks", "brand": "Lay's", "price_inr": 150, "seller_rating": 4.5}, "quantity": 1,
  "expected": "deny"},
 {"case": "Aarav buys chips for Rs 50", "member": "teen", "action": "purchase_item",
  "product": {"category": "snacks", "brand": "Lay's", "price_inr": 50, "seller_rating": 4.5}, "quantity": 1,
  "expected": "allow"},
 {"case": "Dad buys chips for Rs 150", "member": "dad", "action": "purchase_item",
  "product": {"category": "snacks", "brand": "Lay's", "price_inr": 150, "seller_rating": 4.5}, "quantity": 1,
  "expected": "allow"}]
</tests>"""

BROKEN = DRAFT.replace("context.line_total_inr > 100", "resource.colour == 1")
fake_calls = []


def fake_llm(system, user):
    fake_calls.append(user)
    if "BROKEN" in user and "rejected" not in user:
        return BROKEN
    return DRAFT


def test_household_shape(api):
    h = call(api, "GET", "/api/household")
    assert h["household"]["name"] == "Gupta family"
    assert {m["id"] for m in h["members"]} == {"mom", "dad", "didi", "teen", "dadi"}
    assert all("******" in m["phone_masked"] for m in h["members"])
    assert any(r["id"] == "teen-no-energy-drinks" and r["source"] == "base" and "forbid" in r["cedar"]
               for r in h["rules"])
    assert h["mandate"] == {**h["mandate"], "cap_inr": 5000, "used_inr": 0, "remaining_inr": 5000}


def test_chat_web_order_and_orders_listing(api):
    api.scripts.queue.append(sc.script_b)
    r = call(api, "POST", "/api/chat", {"member": "teen", "text": "4 Red Bull and a geometry box"})
    assert r["order"]["status"] == "partially_paid" and r["order"]["channel"] == "web"
    denied = [i for i in r["order"]["items"] if i["decision"] == "deny"]
    assert denied[0]["policy_ids"] == ["teen-no-energy-drinks"] and denied[0]["amazon_search_url"]
    assert any(not d["allowed"] for d in r["decisions"])
    orders = call(api, "GET", "/api/orders", query={"limit": "5"})["orders"]
    assert orders[0]["order_id"] == r["order"]["order_id"] and orders[0]["upi_ref"]
    assert orders[0]["input_type"] == "text" and orders[0]["paid_inr"] == 120
    ev = call(api, "GET", "/api/audit", query={"order_id": r["order"]["order_id"]})["events"]
    assert ev and all(e["order_id"] == r["order"]["order_id"] for e in ev)
    assert {"ts", "type", "actor", "summary", "data"} <= set(ev[0])


def test_chat_image(api):
    img = render_parchi()
    api.fixtures.add(img, transcription())
    api.scripts.queue.append(sc.script_a)
    r = call(api, "POST", "/api/chat", {"member": "didi", "text": "yeh le aao",
                                        "image_base64": base64.b64encode(img).decode(), "media_type": "image/jpeg"})
    assert r["order"]["status"] == "paid" and r["order"]["input_type"] == "image"


def test_chat_validation(api):
    for body in ({"member": "cat", "text": "x"}, {"member": "dad"}, {"member": "dad", "text": "x" * 1001},
                 {"member": "dad", "button_id": "approve:JH-1"}):
        with pytest.raises(ApiError) as e:
            call(api, "POST", "/api/chat", body)
        assert e.value.status == 400


def test_approval_flow_needs_demo_key(api):
    api.scripts.queue.append(sc.script_c)
    r = call(api, "POST", "/api/chat", {"member": "dad", "text": "Rajma chawal for 6 tonight"})
    oid = r["order"]["order_id"]
    assert r["order"]["status"] == "pending_approval"
    pend = call(api, "GET", "/api/approvals")["pending"]
    assert pend[0]["order_id"] == oid and pend[0]["member_name"] == "Dad" and pend[0]["total_inr"] > 1000
    with pytest.raises(ApiError) as e:
        call(api, "POST", f"/api/approvals/{oid}", {"decision": "approve"})
    assert e.value.status == 401
    o = call(api, "POST", f"/api/approvals/{oid}", {"decision": "approve"}, headers={"x-jhola-demo-key": KEY})
    assert o["status"] == "paid" and o["upi_ref"]
    with pytest.raises(ApiError) as e:
        call(api, "POST", f"/api/approvals/{oid}", {"decision": "approve"}, headers={"x-jhola-demo-key": KEY})
    assert e.value.status == 409


def test_rule_draft_activate_enforce_delete(api):
    d = call(api, "POST", "/api/rules/draft", {"text": "Aarav should not buy snacks above Rs 100"})
    assert d["validation"]["ok"] and not d["repaired"] and d["active"] is False
    assert [t["pass"] for t in d["test_results"]] == [True, True, True]
    assert all(r["source"] == "base" for r in call(api, "GET", "/api/household")["rules"])  # never activates

    with pytest.raises(ApiError) as e:
        call(api, "POST", "/api/rules/activate", {"cedar": d["cedar"], "title": d["title"]})
    assert e.value.status == 401
    act = call(api, "POST", "/api/rules/activate", {"cedar": d["cedar"], "title": d["title"]},
               headers={"x-jhola-demo-key": KEY})
    rid = act["rule"]["id"]
    assert f'@id("custom-{rid}")' in act["rule"]["cedar"]
    assert any(r["id"] == rid and r["source"] == "custom" for r in call(api, "GET", "/api/household")["rules"])

    def teen_bhujia():  # Rs 245 snack line for the teen: allowed by base rules, blocked by the custom rule
        cart = yield sc.Call("build_cart", {"items": [{"sku": "haldiram-s-bikaneri-bhujia-1kg", "qty": 1}]})
        res = yield sc.Call("submit_order", {"order_id": cart[0]["order_id"]})
        yield sc.Say(sc.compose_reply(res[0]))

    api.scripts.queue.append(teen_bhujia)
    r = call(api, "POST", "/api/chat", {"member": "teen", "text": "bhujia"})
    assert r["order"]["status"] == "denied"
    assert r["order"]["items"][0]["policy_ids"] == [f"custom-{rid}"]
    assert r["order"]["items"][0]["reason"] == "Teens cannot buy a snack line above Rs 100."

    call(api, "DELETE", f"/api/rules/{rid}", headers={"x-jhola-demo-key": KEY})
    assert all(r["source"] == "base" for r in call(api, "GET", "/api/household")["rules"])
    api.scripts.queue.append(teen_bhujia)
    assert call(api, "POST", "/api/chat", {"member": "teen", "text": "bhujia"})["order"]["status"] == "paid"


def test_rule_draft_repairs_invalid_policy(api):
    d = call(api, "POST", "/api/rules/draft", {"text": "BROKEN rule please"})
    assert d["repaired"] and d["validation"]["ok"]


def test_activate_rejects_invalid(api):
    with pytest.raises(ApiError) as e:
        call(api, "POST", "/api/rules/activate", {"cedar": "forbid ( oops", "title": "x"},
             headers={"x-jhola-demo-key": KEY})
    assert e.value.status == 422


@pytest.mark.parametrize("attack,policy", [
    ("injection", "max-qty-per-line"),
    ("overspend", "house-help-daily-cap"),
    ("forbidden_category", "teen-no-energy-drinks"),
    ("allergen_bypass", "allergy"),
])
def test_redteam_blocked_and_sandboxed(api, attack, policy):
    r = call(api, "POST", "/api/redteam", {"attack": attack})
    assert r["verdict"] == "blocked" and r["payment"] is None and r["simulated_compromised_model"] is True
    assert r["model_proposed"] and any(policy in d["policy_ids"] for d in r["decisions"])
    assert api.repo.list("orders") == [] and api.repo.list("txns") == []  # live state untouched
    assert any(e["type"] == "redteam_run" for e in call(api, "GET", "/api/audit")["events"])


def test_refill_preview_and_window(api):
    with pytest.raises(ApiError):
        call(api, "POST", "/api/refill/run", {"send": False})
    api.scripts.queue.append(sc.script_d)
    r = call(api, "POST", "/api/refill/run", {"send": False}, headers={"x-jhola-demo-key": KEY})
    assert r["sent"] is False and r["order"]["status"] == "draft" and r["order"]["items"]
    # No WhatsApp message from the admin yet -> outside the 24-hour window -> skipped, nothing sent
    r = call(api, "POST", "/api/refill/run", {}, headers={"x-jhola-demo-key": KEY})
    assert r["sent"] is False and "24-hour" in r["skipped"]
    import time

    api.repo.put("wa_last_inbound", api.admin_phone(api.app()), {"at": int(time.time())})
    api.scripts.queue.append(sc.script_d)
    r = call(api, "POST", "/api/refill/run", {}, headers={"x-jhola-demo-key": KEY})
    assert r["sent"] is True and r["message_ids"] == ["mid-1"]


def test_demo_reset_keeps_persona(api):
    api.repo.put("demo_acting", "+911234567890", {"member_id": "dad"})
    api.scripts.queue.append(sc.script_b)
    call(api, "POST", "/api/chat", {"member": "teen", "text": "red bull"})
    r = call(api, "POST", "/api/demo/reset", headers={"x-jhola-demo-key": KEY})
    assert r["ok"] and r["mandate_used_inr"] == 0
    assert api.repo.list("orders") == [] and api.repo.get("demo_acting", "+911234567890")


def test_rate_limit_and_routing(api):
    lim = RateLimiter()
    import os

    os.environ["JHOLA_RATE_WRITE"] = "2"
    try:
        for _ in range(2):
            call(api, "POST", "/api/redteam", {"attack": "injection"}, limiter=lim)
        with pytest.raises(ApiError) as e:
            call(api, "POST", "/api/redteam", {"attack": "injection"}, limiter=lim)
        assert e.value.status == 429
    finally:
        del os.environ["JHOLA_RATE_WRITE"]
    with pytest.raises(ApiError) as e:
        call(api, "GET", "/api/nope")
    assert e.value.status == 404
    with pytest.raises(ApiError) as e:
        call(api, "GET", "/api/chat")
    assert e.value.status == 405


def test_audit_masks_phones(api):
    api.app().audit.log("message_rejected", actor="+919876543210", reason="unknown sender")
    ev = call(api, "GET", "/api/audit")["events"][-1]
    assert ev["actor"] == "+91******3210"


def test_order_ids_not_reused_after_reset(api):
    api.scripts.queue += [sc.script_b, sc.script_b]
    first = call(api, "POST", "/api/chat", {"member": "teen", "text": "x"})["order"]["order_id"]
    api.repo.delete_collection("orders")
    api.repo.delete_collection("counters")  # e.g. a counter created after an old-style reset
    second = call(api, "POST", "/api/chat", {"member": "teen", "text": "x"})["order"]["order_id"]
    assert second != first
