"""End-to-end scenarios through the Strands agent loop with the scripted model."""

from jhola import scenarios as sc


def run(key):
    s = next(x for x in sc.SCENARIOS if x.key == key)
    c = sc.Ctx(live=False, month_spent=s.month_spent_inr)
    s.run(c)
    return c.app


def statuses(app):
    return [o["status"] for o in app.repo.list("orders")]


def test_a_parchi_auto_paid():
    app = run("A")
    [o] = app.repo.list("orders")
    assert o["status"] == "paid" and o["paid_amount_inr"] == 342


def test_b_teen():
    app = run("B")
    [o] = app.repo.list("orders")
    assert o["status"] == "paid" and o["paid_amount_inr"] == 120
    assert o["blocked_lines"][0]["policy_ids"] == ["teen-no-energy-drinks"]


def test_c_recipe_approval():
    app = run("C")
    [o] = app.repo.list("orders")
    assert o["status"] == "paid" and o["paid_amount_inr"] > 1000
    skus = {l["sku"] for l in o["lines"]}
    assert "india-gate-basmati-rice-classic-5kg" not in skus  # in pantry
    assert "tata-sampann-rajma-chitra-1kg" in skus  # substitute for out-of-stock Fortune
    assert any(e["event"] == "approval_requested" for e in app.audit.events())


def test_d_refill():
    app = run("D")
    [o] = app.repo.list("orders")
    assert o["status"] == "paid" and o["member_id"] == "mom"
    assert any(e["event"] == "refill_predicted" for e in app.audit.events())


def test_e_injection_blocked():
    app = run("E")
    assert statuses(app) == ["denied"]
    evs = app.audit.events()
    assert any(e["event"] == "suspicious_content_detected" for e in evs)
    assert any(e["event"] == "policy_evaluated" and "max-qty-per-line" in e["data"]["policy_ids"] for e in evs)
    assert app.repo.list("txns") == []


def test_f_mandate_exhausted():
    app = run("F")
    assert statuses(app) == ["denied"]
    assert app.repo.list("txns") == []
