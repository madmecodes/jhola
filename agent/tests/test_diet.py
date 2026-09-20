"""Rules beyond money: diet profiles, allergies, vrat, caffeine, ordering for someone else, admin commands,
family cart merge and pantry nudges."""

from datetime import timedelta

import pytest

from jhola import scenarios as sc
from jhola.admin import HouseholdAdmin
from jhola.agent import JholaAgent
from jhola.config import DEMO_NOW, Clock
from jhola.domain import Member, normalize_allergen
from jhola.orders import Jhola
from jhola.redteam import run_attack
from jhola.store import InMemoryRepository
from jhola.stub_model import Call, Say, ScriptedModel

NAVRATAN = "haldiram-s-navratan-mix-400g"  # onion, garlic, peanut
JAIN_MIX = "desi-snacks-co-jain-mixture-no-onion-no-garlic-200g"
PEANUT_BUTTER = "pintola-crunchy-peanut-butter-350g"
SNICKERS = "snickers-peanut-45g"
EGGS = "eggoz-farm-fresh-white-eggs-6pcs"
COKE = "coca-cola-coke-750ml"  # 24 mg caffeine per serving
COFFEE = "nescafe-classic-coffee-100g"  # 65 mg
SABUDANA = "rajdhani-sabudana-500g"  # vrat friendly


def line(app, m, sku, qty=1, for_member=None, caffeine=None):
    b = app.hh.find(for_member) if for_member else None
    return app.policy.evaluate_line(m, app.catalog.get(sku), qty, today=app.today_int(), beneficiary=b,
                                    order_caffeine_mg=caffeine)


# ---------- seeded demo household ----------
def test_demo_household_has_dadi_and_teen_allergy(app):
    dadi, teen = app.hh.member("dadi"), app.hh.member("teen")
    assert dadi.role == "elder" and dadi.diet_profile == "jain" and dadi.phone == "+919999900005"
    assert teen.allergies == ["peanut"]
    assert "Jain" in dadi.diet_text() and "peanut" in teen.diet_text()


def test_existing_seeded_household_is_upgraded_not_reset():
    """A table seeded before Dadi existed gets her added and the teen's allergy set, once, without
    touching anything the admin changed."""
    repo = InMemoryRepository()
    app = Jhola(repo, Clock(DEMO_NOW))
    sr = app.repo
    sr.delete("members", "dadi")
    repo.delete("phones", "+919999900005")
    teen = sr.get("members", "teen")
    for k in ("diet_profile", "allergies", "vrat_until", "max_caffeine_mg"):
        teen.pop(k, None)
    sr.put("members", "teen", teen)
    dad = sr.get("members", "dad")
    dad.update(diet_profile="veg", allergies=["milk"])  # the admin's own change
    sr.put("members", "dad", dad)
    app2 = Jhola(repo, Clock(DEMO_NOW))
    assert app2.hh.member("dadi").diet_profile == "jain"
    assert app2.hh.member("teen").allergies == ["peanut"]
    assert app2.hh.member("dad").allergies == ["milk"] and app2.hh.member("dad").diet_profile == "veg"
    assert repo.get("phones", "+919999900005")["member_id"] == "dadi"


# ---------- Cedar dietary policies ----------
def test_jain_blocks_onion_garlic_for_dadi_herself(app, members):
    d = line(app, members["dadi"], NAVRATAN)
    assert not d.allowed and d.policy_ids[0] == "diet-jain"
    assert "Dadi is Jain" in d.reasons[0] and "Dadi Jain hain" in d.reasons_hinglish[0]
    assert line(app, members["dadi"], JAIN_MIX).allowed


def test_ordering_for_dadi_applies_her_diet_to_didi(app, members):
    d = line(app, members["didi"], NAVRATAN, for_member="dadi")
    assert not d.allowed and "diet-jain" in d.policy_ids
    ok = line(app, members["didi"], JAIN_MIX, for_member="dadi")
    assert ok.allowed and "house-help-for-elder" in ok.policy_ids
    # Snacks for herself stay outside Didi's scope
    assert not line(app, members["didi"], JAIN_MIX).allowed


def test_allergy_blocks_for_teen_and_when_others_order_for_him(app, members):
    d = line(app, members["teen"], SNICKERS)
    assert not d.allowed and d.policy_ids == ["allergy"]
    assert "allergic to peanut" in d.reasons[0]
    d2 = line(app, members["dad"], PEANUT_BUTTER, for_member="teen")
    assert not d2.allowed and "allergy" in d2.policy_ids
    assert line(app, members["dad"], PEANUT_BUTTER).allowed  # Dad himself is fine


def test_veg_vegan_eggetarian_profiles(app, members):
    dad = members["dad"]
    dad.diet_profile = "veg"
    assert "diet-vegetarian" in line(app, dad, EGGS).policy_ids
    dad.diet_profile = "eggetarian"
    assert line(app, dad, EGGS).allowed
    dad.diet_profile = "vegan"
    assert "diet-vegan" in line(app, dad, "amul-pure-ghee-1l").policy_ids
    assert line(app, dad, "aashirvaad-shudh-chakki-atta-5kg").allowed
    dad.diet_profile = "none"
    assert line(app, dad, EGGS).allowed


def test_vrat_mode_until_date(app, members):
    mom = members["mom"]
    mom.vrat_until = "2026-10-02"
    assert "vrat-mode" in line(app, mom, NAVRATAN).policy_ids
    assert line(app, mom, SABUDANA).allowed
    assert line(app, mom, "vim-dishwash-bar-200g").allowed if app.catalog.get("vim-dishwash-bar-200g") else True
    app.clock.advance(days=13)  # 3 Oct: the fast is over, Cedar compares context.today
    assert line(app, mom, NAVRATAN).allowed


def test_caffeine_caps(app, members):
    dad = members["dad"]
    assert line(app, dad, COFFEE, qty=5).allowed  # no cap set
    dad.max_caffeine_mg = 80
    assert line(app, dad, COKE, qty=3).allowed  # 72 mg
    d = line(app, dad, COKE, qty=4)  # 96 mg
    assert not d.allowed and d.policy_ids == ["caffeine-cap"] and "80 mg" in d.reasons[0]
    dad.max_caffeine_mg = 0
    assert not line(app, dad, COKE).allowed
    # teens: 100 mg per order by default, when an adult orders a drink FOR the teen
    assert line(app, members["mom"], COKE, qty=4, for_member="teen").allowed  # 96 mg
    d = line(app, members["mom"], COKE, qty=5, for_member="teen")  # 120 mg
    assert not d.allowed and d.policy_ids == ["teen-caffeine-cap"]
    d = line(app, members["mom"], "red-bull-energy-drink-250ml", for_member="teen")
    assert not d.allowed and d.policy_ids == ["teen-no-energy-drinks"]


def test_non_food_ignores_diet(app, members):
    dadi = members["dadi"]
    dadi.allergies = ["milk", "gluten"]
    dadi.vrat_until = "2026-09-30"
    assert line(app, dadi, "camlin-geometry-box-scholar-1pcs").allowed


# ---------- orders: beneficiaries, substitutes, caffeine summed per order ----------
def test_submit_blocks_for_dadi_and_suggests_jain_substitute(app, members):
    o = app.build_cart(members["didi"], [{"sku": NAVRATAN, "qty": 1}], for_member="Dadi")
    assert o["lines"][0]["for_member"] == "dadi"
    res = app.submit_order(members["didi"], o["order_id"])
    assert res["status"] == "denied" and app.repo.list("txns") == []
    b = res["blocked_lines"][0]
    assert b["for"] == "Dadi" and b["policy_ids"][0] == "diet-jain"
    assert b["suggested_substitute"]["sku"] == JAIN_MIX
    o2 = app.build_cart(members["didi"], [{"sku": JAIN_MIX, "qty": 1}], for_member="Dadi")
    assert app.submit_order(members["didi"], o2["order_id"])["status"] == "paid"
    ev = [e for e in app.audit.events() if e["event"] == "policy_evaluated" and e["data"].get("sku") == NAVRATAN]
    assert ev[0]["data"]["for_member"] == "dadi"


def test_per_line_for_member_and_mixed_cart(app, members):
    o = app.build_cart(members["dad"], [{"sku": SNICKERS, "qty": 1, "for_member": "Aarav"},
                                        {"sku": SNICKERS, "qty": 1}])
    res = app.submit_order(members["dad"], o["order_id"])
    assert res["status"] == "paid" and res["payable_inr"] == 45
    assert res["blocked_lines"][0]["for"] == "Aarav" and "allergy" in res["blocked_lines"][0]["policy_ids"]


def test_caffeine_is_summed_over_the_order(app, members):
    dad = members["dad"]
    dad.max_caffeine_mg = 80
    o = app.build_cart(dad, [{"sku": COKE, "qty": 2}, {"sku": COFFEE, "qty": 1}])  # 48 + 65 = 113 mg
    res = app.submit_order(dad, o["order_id"])
    assert res["status"] == "denied"
    assert all("caffeine-cap" in b["policy_ids"] for b in res["blocked_lines"]) and len(res["blocked_lines"]) == 2


def test_check_line_precheck_matches_submit(app, members):
    chk = app.check_line(members["didi"], app.catalog.get(NAVRATAN), 1, "Dadi")
    assert not chk["allowed"] and chk["for"] == "Dadi" and chk["suggested_substitute"]["sku"] == JAIN_MIX
    assert app.check_line(members["didi"], app.catalog.get("nandini-toned-milk-500ml"), 2)["allowed"]
    assert app.repo.list("orders") == []


def test_unknown_for_member_falls_back_to_self(app, members):
    assert app.beneficiary(members["dad"], "Uncle").id == "dad"
    assert app.beneficiary(members["dad"], "dadi").id == "dadi"
    assert app.beneficiary(members["dad"], "self").id == "dad"


# ---------- admin plain-word commands ----------
def test_admin_sets_diet_allergy_vrat_caffeine_with_confirmation(app, members):
    ha = HouseholdAdmin(app)
    mom, dad = members["mom"], members["dad"]
    r = ha.propose_diet_change(mom, "Dad", diet_profile="Jain")
    assert r["needs_confirmation"] and "diet none -> jain" in r["summary"]
    assert dad.diet_profile == "none"  # nothing before Yes
    assert ha.confirm(mom, r["action_id"]).startswith("Done. Dad: Jain")
    assert app.hh.member("dad").diet_profile == "jain"
    assert Member.from_doc(app.repo.get("members", "dad")).diet_profile == "jain"

    r = ha.propose_diet_change(mom, "Aarav", add_allergies=["moongfali", "dairy"])
    assert "peanut, milk" in r["summary"]
    ha.confirm(mom, r["action_id"])
    assert app.hh.member("teen").allergies == ["peanut", "milk"]

    r = ha.propose_diet_change(mom, "Mom", vrat_until="2026-10-02")
    ha.confirm(mom, r["action_id"])
    assert app.hh.member("mom").vrat_until == "2026-10-02"
    assert not line(app, mom, NAVRATAN).allowed

    r = ha.propose_diet_change(mom, "Aarav", max_caffeine_mg=80)
    ha.confirm(mom, r["action_id"])
    assert app.hh.member("teen").max_caffeine_mg == 80
    r = ha.propose_diet_change(mom, "Aarav", max_caffeine_mg=-1)
    ha.confirm(mom, r["action_id"])
    assert app.hh.member("teen").max_caffeine_mg is None
    assert any(e["event"] == "member_diet_changed" for e in app.audit.events())


def test_admin_diet_errors(app, members):
    ha = HouseholdAdmin(app)
    mom = members["mom"]
    assert "error" in ha.propose_diet_change(mom, "Nobody", diet_profile="veg")
    assert "error" in ha.propose_diet_change(mom, "Dad", diet_profile="keto")
    assert "allergen" in ha.propose_diet_change(mom, "Dad", add_allergies=["kryptonite"])["error"]
    assert "error" in ha.propose_diet_change(mom, "Dad", vrat_until="someday")
    assert "error" in ha.propose_diet_change(mom, "Dad")


def test_non_admin_cannot_set_diet(app, members):
    from jhola.admin import NotAllowed

    with pytest.raises(NotAllowed):
        HouseholdAdmin(app).propose_diet_change(members["dad"], "Aarav", add_allergies=["peanut"])
    assert any(e["event"] == "admin_action_denied" for e in app.audit.events())


def test_normalize_allergen_words():
    assert normalize_allergen("Peanuts") == "peanut" and normalize_allergen("moongfali") == "peanut"
    assert normalize_allergen("dry fruits") == "tree_nut" and normalize_allergen("gehun") == "gluten"
    assert normalize_allergen("anda") == "egg" and normalize_allergen("plastic") is None


def test_admin_diet_via_agent_tool_yes_no_buttons(app, members):
    def script():
        yield Call("propose_diet_change", {"member_name": "Dadi", "add_allergies": ["peanuts"]})
        yield Say("Confirm?")

    agent = JholaAgent(app, vision=None)
    r = agent.handle_message(members["mom"].phone, "Dadi is allergic to peanuts", model=ScriptedModel(script))
    assert [b["title"] for b in r.buttons] == ["Yes", "No"] and "allergies -> peanut" in r.text
    r2 = agent.handle_button(members["mom"].phone, r.buttons[0]["id"])
    assert r2.text.startswith("Done.") and app.hh.member("dadi").allergies == ["peanut"]


# ---------- family cart merge ----------
def test_duplicate_order_asks_second_requester(app, members):
    dad, mom = members["dad"], members["mom"]
    o1 = app.build_cart(dad, [{"sku": "nandini-toned-milk-500ml", "qty": 2}])
    assert app.submit_order(dad, o1["order_id"])["status"] == "paid"
    app.clock.advance(minutes=20)
    o2 = app.build_cart(mom, [{"sku": "nandini-toned-milk-1l", "qty": 1}, {"sku": "tata-salt-iodised-salt-1kg", "qty": 1}])
    assert o2["recently_ordered_by_family"][0]["by"] == "Dad" and o2["recently_ordered_by_family"][0]["minutes_ago"] == 20
    res = app.submit_order(mom, o2["order_id"])
    assert res["status"] == "needs_confirmation" and "Dad ne 20 min pehle" in res["question"]
    assert app.repo.list("txns").__len__() == 1
    # Yes: the whole cart is ordered
    res = app.submit_order(mom, o2["order_id"], confirm_duplicates=True)
    assert res["status"] == "paid" and len(res["allowed_lines"]) == 2


def test_duplicate_no_drops_the_line(app, members):
    dad, mom = members["dad"], members["mom"]
    o1 = app.build_cart(dad, [{"sku": "nandini-toned-milk-500ml", "qty": 2}])
    app.submit_order(dad, o1["order_id"])
    o2 = app.build_cart(mom, [{"sku": "nandini-toned-milk-500ml", "qty": 2}, {"sku": "tata-salt-iodised-salt-1kg", "qty": 1}])
    res = app.drop_duplicates(mom, o2["order_id"])
    assert res["status"] == "paid" and [l["label"] for l in res["allowed_lines"]] == ["Tata Salt Iodised Salt 1kg (Rs 28)"]
    o3 = app.build_cart(mom, [{"sku": "nandini-toned-milk-500ml", "qty": 2}])
    assert app.drop_duplicates(mom, o3["order_id"])["status"] == "cancelled"


def test_duplicate_window_and_own_orders(app, members):
    dad, mom = members["dad"], members["mom"]
    o1 = app.build_cart(dad, [{"sku": "nandini-toned-milk-500ml", "qty": 2}])
    app.submit_order(dad, o1["order_id"])
    o_own = app.build_cart(dad, [{"sku": "nandini-toned-milk-500ml", "qty": 2}])
    assert "recently_ordered_by_family" not in o_own  # your own repeat is not a family duplicate
    app.clock.advance(minutes=61)
    o2 = app.build_cart(mom, [{"sku": "nandini-toned-milk-500ml", "qty": 2}])
    assert "recently_ordered_by_family" not in o2
    assert app.submit_order(mom, o2["order_id"])["status"] == "paid"


def test_duplicate_buttons_through_agent(app, members):
    dad, mom = members["dad"], members["mom"]
    o1 = app.build_cart(dad, [{"sku": "nandini-toned-milk-500ml", "qty": 2}])
    app.submit_order(dad, o1["order_id"])

    def script():
        cart = yield Call("build_cart", {"items": [{"sku": "nandini-toned-milk-500ml", "qty": 2}]})
        res = yield Call("submit_order", {"order_id": cart[0]["order_id"]})
        yield Say(sc.compose_reply(res[0]))

    agent = JholaAgent(app, vision=None)
    r = agent.handle_message(mom.phone, "2 doodh", model=ScriptedModel(script))
    assert "Dad ne 0 min pehle" in r.text and [b["id"].split(":")[0] for b in r.buttons] == ["dupyes", "dupno"]
    r2 = agent.handle_button(mom.phone, r.buttons[1]["id"])
    assert "cancel" in r2.text and app.get_order(r.order_ids[0])["status"] == "cancelled"


# ---------- pantry nudges ----------
def test_pantry_nudge_on_recent_purchase(app, members):
    mom = members["mom"]
    o1 = app.build_cart(mom, [{"sku": "tata-salt-iodised-salt-1kg", "qty": 1}])
    app.submit_order(mom, o1["order_id"])
    app.clock.advance(days=3)
    o2 = app.build_cart(members["dad"], [{"sku": "tata-salt-iodised-salt-1kg", "qty": 1}])
    nudge = o2["probably_at_home"][0]
    assert nudge["item"].startswith("Tata Salt") and nudge["by"] == "Mom"
    assert "recently_ordered_by_family" not in o2  # 3 days later is not a duplicate


def test_pantry_shelf_life_caps_estimate(app):
    st = app.pantry.status_for_sku("nandini-toned-milk-500ml", app.clock.today())
    assert st.get("last_bought")
    assert (app.clock.today() - __import__("datetime").date.fromisoformat(st["expected_run_out"])).days < 10


# ---------- scenarios and red team ----------
def _run(key):
    s = next(x for x in sc.SCENARIOS if x.key == key)
    c = sc.Ctx(live=False, month_spent=s.month_spent_inr)
    s.run(c)
    return c.app


def test_scenario_g_dadi_jain():
    app = _run("G")
    orders = sorted(app.repo.list("orders"), key=lambda o: o["order_id"])
    assert [o["status"] for o in orders] == ["denied", "paid"]
    assert orders[0]["blocked_lines"][0]["policy_ids"][0] == "diet-jain"
    assert orders[0]["blocked_lines"][0]["suggested_substitute"]["sku"] == JAIN_MIX
    assert orders[1]["lines"][0]["sku"] == JAIN_MIX and orders[1]["lines"][0]["for_member"] == "dadi"
    assert len(app.repo.list("txns")) == 1


def test_scenario_h_teen_allergy():
    app = _run("H")
    orders = sorted(app.repo.list("orders"), key=lambda o: o["order_id"])
    assert [o["status"] for o in orders] == ["denied", "paid"]
    assert all("allergy" in b["policy_ids"] for b in orders[0]["blocked_lines"])
    assert any(b.get("suggested_substitute") for b in orders[0]["blocked_lines"])
    assert "peanut" not in (app.catalog.get(orders[1]["lines"][0]["sku"]).get("allergens") or [])


def test_redteam_allergen_bypass_blocked(app):
    r = run_attack(app, "allergen_bypass")
    assert r["verdict"] == "blocked" and r["payment"] is None
    assert all(not d["allowed"] and "allergy" in d["policy_ids"] for d in r["decisions"] if d["action"] == "purchase_item")
    assert app.repo.list("orders") == []
