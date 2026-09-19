"""Multi-household behaviour: tenancy, onboarding, family admin in plain words, approvals and the
24-hour window, learned brands, delegation with expiry, privacy."""

import time

import pytest
from helpers import World, body, button_ids, order, order_word, propose, staple_between, to

from jhola.domain import DEMO_HOUSEHOLD_ID
from jhola.onboarding import parse_amount, parse_name
from jhola.phones import mask_in_text, mask_phone, to_e164, valid_mobile
from jhola.stub_model import Call, Say

PRIYA, SUNITA, AARAV, RAHUL = "+919811100001", "+919811100002", "+919811100003", "+919822200001"


# ---------- phones ----------
def test_phone_normalization_and_masking():
    for raw in ("98765 43210", "+91 98765-43210", "09876543210", "919876543210", "0091 9876543210"):
        assert to_e164(raw) == "+919876543210"
    assert to_e164("+1 415 555 0100") == "+14155550100"
    assert valid_mobile("+919876543210") and not valid_mobile("+911234567890") and not valid_mobile("+9198")
    assert mask_phone("+919876543210") == "+91******3210"
    assert mask_in_text("call +91 98765 43210 now") == "call +91******3210 now"


# ---------- onboarding ----------
def test_onboarding_parsers():
    assert parse_name("I am Priya, Sharma home") == ("Priya", "Sharma home")
    assert parse_name("mera naam sunita hai") == ("Sunita", "")
    assert parse_name("Verma family") == ("Verma", "Verma family")
    assert [parse_amount(x) for x in ("8000", "Rs 7,500", "5k", "8 hazaar", "ok")] == [8000, 7500, 5000, 8000, None]


def test_unknown_number_is_onboarded_in_three_questions():
    w = World()
    first = w.say(PRIYA, "2 kg atta bhej do")
    assert "1/3" in body(first[0]) and "jhola-phi.vercel.app/privacy" in body(first[0])
    q2 = w.say(PRIYA, "Priya, Sharma home")
    assert "2/3" in body(q2[0]) and "SIMULATED" in body(q2[0]) and button_ids(q2[0]) == ["onb:default"]
    q3 = w.tap(PRIYA, "onb:default")  # default budget Rs 5000
    assert "3/3" in body(q3[0]) and "5000" in body(q3[0])
    done = w.say(PRIYA, "1500")
    text = body(done[0])
    assert "Sharma home" in text and "SIMULATED" in text and "Add Sunita didi" in text and "photo" in text
    idx = w.ch.dir.lookup(PRIYA)
    assert idx["household_id"].startswith("hh-") and not idx["demo"]
    app = w.app(idx["household_id"])
    [admin] = app.hh.members
    assert (admin.role, admin.display, admin.phone) == ("admin", "Priya", PRIYA)
    assert app.hh.mandate["monthly_cap_inr"] == 5000 and app.hh.mandate["per_payment_approval_above_inr"] == 1500
    assert app.month_spent() == 0 and app.hh.preferences == {}
    assert w.repo.get("onboarding", PRIYA) is None
    assert [e["event"] for e in app.audit.events()] == ["household_created"]


def test_household_of_one_orders_and_pays():
    w = World()
    hid = w.onboard(PRIYA)
    item = staple_between(100, 500)
    out = w.say(PRIYA, "order", order(item["id"]))
    assert "SIMULATED" in body(out[0])
    [o] = w.app(hid).repo.list("orders")
    assert o["status"] == "paid" and w.app(hid).month_spent() == item["price_inr"]


def test_onboarding_can_be_cancelled():
    w = World()
    w.say(PRIYA, "hi")
    w.say(PRIYA, "stop")
    assert w.repo.get("onboarding", PRIYA) is None and w.ch.dir.lookup(PRIYA) is None


# ---------- admin manages family in plain words ----------
def test_admin_adds_member_only_after_yes_and_member_is_recognised():
    w = World()
    hid = w.onboard(PRIYA)
    out = w.say(PRIYA, "Add Sunita didi +91 98111 00002, groceries only, 500 a day",
                propose("propose_add_member", {"name": "Sunita didi", "phone": "98111 00002", "role": "house_help",
                                               "daily_limit_inr": 500, "categories": ["groceries"]}))
    text = body(out[0])
    assert "Sunita didi" in text and "+91******0002" in text and "500 a day" in text and SUNITA not in text
    yes, no = button_ids(out[0])
    assert yes.startswith("confirm:") and no.startswith("cancel:")
    assert w.ch.dir.lookup(SUNITA) is None and len(w.app(hid).hh.members) == 1  # nothing created yet
    done = w.tap(PRIYA, yes)
    assert "Sunita didi" in body(done[0])
    m = w.app(hid).hh.find("sunita")
    assert (m.role, m.phone, m.daily_cap_inr, m.allowed_categories) == (
        "house_help", SUNITA, 500, ["staples", "dairy", "vegetables", "fruits"])
    assert w.tap(PRIYA, yes) and "pending nahi" in body(w.t.payloads[-1])  # a second tap does nothing
    # the invited number is recognised and greeted by name, no setup
    hello = w.say(SUNITA, "hi")
    assert len(hello) == 1 and "Namaste Sunita didi" in body(hello[0]) and "Priya" in body(hello[0])
    assert "500 a day" in body(hello[0]) and "1/3" not in body(hello[0])
    assert w.app(hid).hh.find("sunita").welcomed


def test_no_means_nothing_changes():
    w = World()
    hid = w.onboard(PRIYA)
    out = w.say(PRIYA, "add", propose("propose_add_member", {"name": "Aarav", "phone": AARAV, "role": "teen"}))
    w.tap(PRIYA, button_ids(out[0])[1])
    assert w.ch.dir.lookup(AARAV) is None and len(w.app(hid).hh.members) == 1


def test_custom_condition_is_drafted_validated_and_activated_with_the_member():
    w = World()
    hid = w.onboard(PRIYA)
    out = w.say(PRIYA, "Add my son Aarav 9811100003, only stationery and snacks, no chocolate",
                propose("propose_add_member", {"name": "Aarav", "phone": "9811100003", "role": "teen",
                                               "categories": ["stationery", "snacks"],
                                               "custom_conditions": "no chocolate"}))
    assert "Extra rule: No chocolate for aarav" in body(out[0])
    assert w.app(hid).repo.list("rules") == []  # drafted, not active
    w.tap(PRIYA, button_ids(out[0])[0])
    app = w.app(hid)
    [rule] = app.repo.list("rules")
    assert rule["active"] and f"custom-{rule['id']}" in rule["cedar"]
    aarav = app.hh.find("aarav")
    choc = {"id": "x", "name": "Silk", "brand": "Cadbury", "category": "snacks", "tags": ["chocolate"],
            "price_inr": 80, "seller_rating": 4.5}
    d = app.policy.evaluate_line(aarav, choc, 1, today=app.today_int())
    assert not d.allowed and f"custom-{rule['id']}" in d.policy_ids
    assert app.policy.evaluate_line(aarav, {**choc, "tags": ["chips"]}, 1, today=app.today_int()).allowed
    drink = {**choc, "category": "energy_drinks", "tags": ["energy"]}
    assert not app.policy.evaluate_line(aarav, drink, 1, today=app.today_int()).allowed  # teen template


def test_a_phone_belongs_to_one_household_only():
    w = World()
    w.onboard(PRIYA)
    w.onboard(RAHUL, name="Rahul")
    out = w.say(RAHUL, "add", propose("propose_add_member", {"name": "Priya", "phone": PRIYA, "role": "adult"}))
    assert out[0]["type"] == "text"  # no Yes / No: the proposal was refused


def test_non_admin_cannot_manage_members_or_rules_and_the_attempt_is_audited():
    w = World()
    hid = w.onboard(PRIYA)
    w.add_member(PRIYA, name="Sunita didi", phone=SUNITA, role="house_help")
    w.say(SUNITA, "hi")
    # 1. through the model: the member only has the request_admin_change tool, which records the attempt
    w.say(SUNITA, "add my sister 9811100009", propose("request_admin_change", {"request": "add my sister"}))
    # 2. a model that tries the admin tool anyway: it does not exist for this member
    from jhola.agent import Turn, make_tools
    app = w.app(hid)
    sunita = app.hh.find("sunita")
    names = {t.tool_name for t in make_tools(app, Turn(sunita, "", None, None), None)}
    assert "request_admin_change" in names and not any(n.startswith("propose_") for n in names)
    # 3. a forged confirm button for a real pending action
    out = w.say(PRIYA, "add", propose("propose_add_member", {"name": "Aarav", "phone": AARAV, "role": "teen"}))
    forged = w.tap(SUNITA, button_ids(out[0])[0])
    assert "Only the household admin" in body(forged[0])
    assert w.ch.dir.lookup(AARAV) is None
    # 4. directly against the service
    from jhola.admin import HouseholdAdmin, NotAllowed
    with pytest.raises(NotAllowed):
        HouseholdAdmin(app).propose_rule(sunita, "let me buy anything")
    denied = [e for e in w.app(hid).audit.events() if e["event"] == "admin_action_denied"]
    assert len(denied) == 3 and {e["actor"] for e in denied} == {"sunita"}


def test_admin_lists_changes_limits_budget_rules_and_removes_member():
    w = World()
    hid = w.onboard(PRIYA)
    w.add_member(PRIYA, name="Aarav", phone=AARAV, role="teen")

    def both():
        m = yield Call("list_members", {})
        s = yield Call("spending_summary", {})
        yield Say(f"{[x['name'] for x in m[0]['members']]} spent {s[0]['spent_inr']} of {s[0]['budget_inr']}")

    assert "['Priya', 'Aarav'] spent 0 of 5000" in body(w.say(PRIYA, "list members", both)[0])

    out = w.say(PRIYA, "limit", propose("propose_change_limit", {"member_name": "aarav", "daily_limit_inr": 200}))
    w.tap(PRIYA, button_ids(out[0])[0])
    assert w.app(hid).hh.find("aarav").daily_cap_inr == 200

    out = w.say(PRIYA, "budget 8000", propose("propose_budget_change", {"monthly_budget_inr": 8000,
                                                                       "approval_threshold_inr": 1200}))
    assert "5000 -> Rs 8000" in body(out[0])
    w.tap(PRIYA, button_ids(out[0])[0])
    app = w.app(hid)
    assert app.upi.get(app.mandate_id)["monthly_cap_inr"] == 8000
    assert app.hh.mandate["per_payment_approval_above_inr"] == 1200

    out = w.say(PRIYA, "No chocolate for Aarav", propose("propose_rule", {"rule_text": "No chocolate for Aarav"}))
    assert "New rule" in body(out[0]) and "deny" in body(out[0])
    w.tap(PRIYA, button_ids(out[0])[0])

    def rules():
        r = yield Call("list_rules", {})
        yield Say("; ".join(f"{x['number']}. {x['title']}" for x in r[0]["rules"]))

    assert "1. No chocolate for aarav" in body(w.say(PRIYA, "show my rules", rules)[0])
    out = w.say(PRIYA, "remove rule 1", propose("propose_remove_rule", {"number": 1}))
    w.tap(PRIYA, button_ids(out[0])[0])
    assert [r["active"] for r in w.app(hid).repo.list("rules")] == [False]

    out = w.say(PRIYA, "remove aarav", propose("propose_remove_member", {"member_name": "Aarav"}))
    w.tap(PRIYA, button_ids(out[0])[0])
    assert w.ch.dir.lookup(AARAV) is None and w.app(hid).hh.find("aarav") is None
    assert "1/3" in body(w.say(AARAV, "hi")[0])  # a removed number is a stranger again


# ---------- ordering, approvals, the 24-hour window ----------
def family(w):
    hid = w.onboard(PRIYA)
    w.add_member(PRIYA, name="Sunita didi", phone=SUNITA, role="house_help", daily_limit_inr=500,
                 categories=["groceries"])
    w.say(SUNITA, "hi")
    return hid


def test_within_limit_autopays_over_limit_goes_to_the_admin_phone_and_approval_pays():
    w = World()
    hid = family(w)
    item = staple_between(250, 500)
    out = w.say(SUNITA, "atta", order(item["id"]))
    assert "SIMULATED" in body(to(out, SUNITA)[0]) and to(out, PRIYA) == []
    out = w.say(SUNITA, "one more", order(item["id"]))  # 2 x price is above her Rs 500 a day
    [ask] = to(out, PRIYA)  # the approval request reaches the ADMIN'S real phone
    assert "Sunita didi wants to order" in body(ask) and "daily limit" in body(ask)
    approve = button_ids(ask)[0]
    pending = [o for o in w.app(hid).repo.list("orders") if o["status"] == "pending_approval"]
    assert len(pending) == 1 and pending[0]["approval_delivered"] == [PRIYA]
    assert "Only the household admin" in body(w.tap(SUNITA, approve)[0])  # she cannot approve her own order
    out = w.tap(PRIYA, approve)
    assert "Approved" in body(to(out, PRIYA)[0]) and "Priya ne approve" in body(to(out, SUNITA)[0])
    app = w.app(hid)
    assert [o["status"] for o in app.repo.list("orders")] == ["paid", "paid"]
    assert app.month_spent() == 2 * item["price_inr"]


def test_category_outside_personal_scope_is_blocked():
    w = World()
    hid = family(w)
    from jhola.orders import shared_catalog
    soap = next(i for i in shared_catalog().items if i["category"] == "cleaning" and i["in_stock"]
                and i["seller_rating"] >= 4 and i["price_inr"] < 400)
    w.say(SUNITA, "soap", order(soap["id"]))
    [o] = w.app(hid).repo.list("orders")
    assert o["status"] == "denied" and "member-outside-category-scope" in o["blocked_lines"][0]["policy_ids"]


def test_admin_outside_24h_window_keeps_approval_pending_and_surfaces_it_first():
    w = World()
    hid = family(w)
    item = staple_between(250, 500)
    w.repo.put("wa_last_inbound", PRIYA, {"phone": PRIYA, "at": int(time.time()) - 25 * 3600})
    out = w.say(SUNITA, "order", order(item["id"], 2))
    assert to(out, PRIYA) == []  # WhatsApp would reject a free-form message to her now
    assert "Priya" in body(out[-1]) and "hi" in body(out[-1]) and "pending" in body(out[-1])
    [o] = w.app(hid).repo.list("orders")
    assert o["status"] == "pending_approval" and not o.get("approval_delivered")
    assert any(e["event"] == "notification_held" for e in w.app(hid).audit.events())

    def chat():
        yield Say("Namaste Priya")

    out = w.say(PRIYA, "hello", chat)  # the admin is back: pending approvals come first
    assert "Pending approval" in body(out[0]) and button_ids(out[0])[0] == f"approve:{o['order_id']}"
    assert body(out[1]) == "Namaste Priya"
    out = w.say(PRIYA, "hello again", chat)
    assert len(out) == 1  # not repeated
    w.tap(PRIYA, f"approve:{o['order_id']}")
    assert w.app(hid).get_order(o["order_id"])["status"] == "paid"


# ---------- delegation with expiry, enforced by Cedar through context.today ----------
def test_temporary_delegation_expires_in_cedar():
    w = World()
    hid = family(w)
    item = staple_between(250, 500)
    out = w.say(PRIYA, "Didi can spend 1500 this week",
                propose("propose_delegation", {"member_name": "Sunita", "amount_inr": 1500,
                                               "until_date": "2026-09-27"}))
    assert "2026-09-27" in body(out[0])
    w.tap(PRIYA, button_ids(out[0])[0])
    [rule] = w.app(hid).repo.list("rules")
    assert (rule["kind"], rule["expires_on"], rule["cap_inr"]) == ("delegation", "2026-09-27", 1500)

    w.say(SUNITA, "big order", order(item["id"], 3))  # above Rs 500 a day and maybe above the threshold
    [o] = w.app(hid).repo.list("orders")
    assert o["status"] == "paid"
    ev = [e for e in w.app(hid).audit.events(o["order_id"]) if e["event"] == "policy_evaluated"][-1]
    assert ev["data"]["cedar_request"]["context"]["today"] == 20260920

    app = w.app(hid)
    sunita = app.hh.find("sunita")
    total = item["price_inr"]
    assert sunita.delegation["until"] == 20260927
    allow = app.policy.evaluate_payment("auto_pay", sunita, total, 0, 600, today=20260927,
                                        member_spent_delegated_inr=600)
    expired = app.policy.evaluate_payment("auto_pay", sunita, total, 0, 600, today=20260928,
                                          member_spent_delegated_inr=600)
    used_up = app.policy.evaluate_payment("auto_pay", sunita, total, 0, 600, today=20260921,
                                          member_spent_delegated_inr=1500)
    assert allow.allowed and not expired.allowed and not used_up.allowed
    assert "member-daily-limit" in expired.policy_ids

    w.clock.advance(days=8)  # next week the same order needs approval again
    w.repo.put("wa_last_inbound", PRIYA, {"phone": PRIYA, "at": int(time.time())})
    w.say(SUNITA, "again", order(item["id"], 2))
    assert [x["status"] for x in w.app(hid).repo.list("orders")] == ["paid", "pending_approval"]


# ---------- learned usual brands ----------
def test_new_household_starts_with_sensible_defaults_and_learns_brands():
    w = World()
    hid = w.onboard(PRIYA)
    app = w.app(hid)
    first = app.resolver.resolve("atta")
    picked = app.catalog.get(first["sku"])
    assert first["source"] == "search" and picked["in_stock"] and picked["seller_rating"] >= 4.0
    same_word = [i["price_inr"] for i in app.catalog.items if "atta" in i["tags"] and i["in_stock"]]
    assert min(same_word) < picked["price_inr"] < max(same_word)  # mid-priced, not the extremes

    other = next(i for i in app.catalog.items if "atta" in i["tags"] and i["in_stock"]
                 and i["seller_rating"] >= 4.0 and i["id"] != first["sku"])

    def choose():
        r = yield Call("remember_choice", {"word": "2 kg Atta", "sku": other["id"]})
        yield Say(f"Yaad rakha: {r[0]['label']}")

    w.say(PRIYA, "atta hamesha yeh wala", choose)
    again = w.app(hid).resolver.resolve("atta")
    assert (again["sku"], again["source"]) == (other["id"], "preference")
    assert DEMO_HOUSEHOLD_ID != hid and w.app(DEMO_HOUSEHOLD_ID).resolver.resolve("atta")["sku"] != other["id"] \
        or other["id"] == "aashirvaad-shudh-chakki-atta-5kg"

    # paying for a default pick confirms it, but never overrides an explicit choice
    w.say(PRIYA, "namak", order_word("namak"))
    prefs = w.app(hid).hh.preferences
    assert prefs["namak"]["source"] == "order" and prefs["atta"]["source"] == "choice"
    w.say(PRIYA, "atta", order_word("atta"))
    assert w.app(hid).hh.preferences["atta"]["sku"] == other["id"]


# ---------- isolation ----------
def test_two_households_never_see_each_other():
    w = World()
    a = family(w)
    b = w.onboard(RAHUL, name="Rahul, Mehta house", budget="9000", threshold="2000")
    item = staple_between(250, 500)
    w.say(SUNITA, "order", order(item["id"]))
    w.say(SUNITA, "order", order(item["id"]))  # pending approval in A
    w.llm_member = "priya"
    out = w.say(PRIYA, "rule", propose("propose_rule", {"rule_text": "No chocolate for me"}))
    w.tap(PRIYA, button_ids(out[0])[0])
    w.app(a).hh.learn_preference("atta", item["id"])

    A, B = w.app(a), w.app(b)
    assert len(A.repo.list("orders")) == 2 and len(A.repo.list("rules")) == 1 and A.repo.list("txns")
    for c in ("orders", "txns", "rules", "purchases", "prefs", "sessions", "pending_actions"):
        assert B.repo.list(c) == [], c
    assert [e["event"] for e in B.audit.events()] == ["household_created"]
    assert [m.id for m in B.hh.members] == ["rahul"] and B.hh.preferences == {} and B.policy.custom_rules == []
    assert B.month_spent() == 0 and B.pending_approvals() == [] and B.hh.mandate["monthly_cap_inr"] == 9000
    assert A.mandate_id != B.mandate_id

    # B's admin cannot approve, confirm or even see A's order
    oid = A.pending_approvals()[0]["order_id"]
    assert "no such order" in body(w.tap(RAHUL, f"approve:{oid}")[0])
    assert A.get_order(oid)["status"] == "pending_approval"

    # order ids and audit sequences are per household, and B's first order does not touch A's
    w.say(RAHUL, "order", order(item["id"]))
    assert w.app(b).repo.list("orders")[0]["order_id"].endswith("-0001")
    assert len(w.app(a).repo.list("orders")) == 2

    # physical layout: every household document sits in an hh#<id># partition
    allowed_global = {"households", "phones", "onboarding", "wa_last_inbound", "demo_acting", "web_jobs"}
    for name in w.repo._data:
        assert name in allowed_global or name.startswith(("hh#" + a + "#", "hh#" + b + "#", "hh#_system#",
                                                          "hh#" + DEMO_HOUSEHOLD_ID + "#")), name


# ---------- privacy ----------
def test_member_can_leave_and_last_admin_deletes_the_household():
    w = World()
    hid = family(w)
    w.say(SUNITA, "x", order(staple_between(100, 400)["id"]))
    out = w.say(SUNITA, "Delete my data")
    assert button_ids(out[0]) == ["leave:yes", "leave:no"] and w.ch.dir.lookup(SUNITA)
    w.tap(SUNITA, "leave:yes")
    app = w.app(hid)
    assert w.ch.dir.lookup(SUNITA) is None and app.hh.find("sunita") is None
    assert app.repo.get("sessions", SUNITA) is None and w.repo.get("wa_last_inbound", SUNITA) is None
    assert len(app.repo.list("orders")) == 1  # the household's record stays
    assert any(e["event"] == "member_left" for e in app.audit.events())

    out = w.say(PRIYA, "leave")
    assert "whole household" in body(out[0])
    w.tap(PRIYA, "leave:no")
    assert w.ch.dir.lookup(PRIYA)
    w.say(PRIYA, "leave")
    w.tap(PRIYA, "leave:yes")
    assert w.ch.dir.lookup(PRIYA) is None and w.repo.get("households", hid) is None
    assert not [k for k, v in w.repo._data.items() if k.startswith(f"hh#{hid}#") and v]
    assert "1/3" in body(w.say(PRIYA, "hi")[0])


def test_demo_owner_keeps_persona_commands_and_cannot_delete_the_demo():
    owner = "+916300000001"
    import jhola.config as config
    old, config.ADMIN_PHONE = config.ADMIN_PHONE, owner
    try:
        w = World(demo={owner})
        assert "Didi" in body(w.say(owner, "/as didi")[0])
        assert "/as mom" in body(w.say(owner, "/help")[0])
        assert "demo household" in body(w.say(owner, "delete my data")[0])
        assert w.ch.dir.lookup(owner) == {"household_id": DEMO_HOUSEHOLD_ID, "member_id": "mom", "demo": True}
        # an ordinary household's admin never sees or can use the persona switch
        w.onboard(PRIYA)
        assert "/as" not in body(w.say(PRIYA, "/help")[0])

        def chat():
            yield Say("ok")

        w.say(PRIYA, "/as didi", chat)
        assert w.repo.get("demo_acting", PRIYA) is None
    finally:
        config.ADMIN_PHONE = old


def test_logs_mask_phone_numbers(caplog):
    import logging
    w = World()
    with caplog.at_level(logging.INFO, logger="jhola.whatsapp"):
        w.say(PRIYA, "hi")
    dumped = " ".join(str(r.__dict__) for r in caplog.records)
    assert PRIYA not in dumped and PRIYA.lstrip("+") not in dumped and "+91******0001" in dumped
    assert all(s["to"] == "+91******0001" for s in w.ch.sent)


def test_demo_admin_follows_the_configured_admin_phone():
    import jhola.config as config
    from jhola.household import Directory
    from jhola.store import InMemoryRepository
    repo = InMemoryRepository()
    Directory(repo).ensure_demo()  # seeded while JHOLA_ADMIN_PHONE was the placeholder
    old, config.ADMIN_PHONE = config.ADMIN_PHONE, "+916300000002"
    try:
        d = Directory(repo)
        d.ensure_demo({"+916300000002"})
        assert d.load(DEMO_HOUSEHOLD_ID).member_by_phone("+916300000002").id == "mom"
        assert d.lookup("+916300000002") == {"household_id": DEMO_HOUSEHOLD_ID, "member_id": "mom", "demo": True}
    finally:
        config.ADMIN_PHONE = old
