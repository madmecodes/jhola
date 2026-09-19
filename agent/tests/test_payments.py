"""Payment gating: money only moves after a Cedar allow."""

from dataclasses import replace

import pytest

from jhola.policy import PaymentAuthorization
from jhola.upi import PaymentRejected

DIDI_ITEMS = [
    {"sku": "nandini-toned-milk-500ml", "qty": 2},
    {"sku": "freshfarm-onion-1kg", "qty": 1},
    {"sku": "tata-sampann-unpolished-toor-dal-500g", "qty": 1},
]


def txns(app):
    return app.repo.list("txns")


def test_debit_without_authorization_rejected(app):
    with pytest.raises(PaymentRejected):
        app.upi.debit(app.mandate_id, None)
    fake = PaymentAuthorization("JH-X", 100, "auto_pay", "dad", ("mandate-auto-pay",), "00" * 32)
    with pytest.raises(PaymentRejected):
        app.upi.debit(app.mandate_id, fake)
    assert txns(app) == []


def test_tampered_authorization_rejected(app, members):
    d = app.policy.evaluate_payment("auto_pay", members["dad"], 100, 0, 0)
    auth = app.policy.authorize_payment(d, "JH-1", 100, "dad")
    with pytest.raises(PaymentRejected):
        app.upi.debit(app.mandate_id, replace(auth, amount_inr=5000))
    assert app.upi.debit(app.mandate_id, auth)["status"] == "SUCCESS"


def test_cannot_authorize_from_deny_or_approval_request(app, members):
    deny = app.policy.evaluate_payment("auto_pay", members["dad"], 1500, 0, 0)
    with pytest.raises(PermissionError):
        app.policy.authorize_payment(deny, "JH-1", 1500, "dad")
    req = app.policy.evaluate_payment("request_approval", members["dad"], 1500, 0, 0)
    assert req.allowed
    with pytest.raises(PermissionError):
        app.policy.authorize_payment(req, "JH-1", 1500, "dad")


def test_authorization_must_match_amount_and_member(app, members):
    d = app.policy.evaluate_payment("auto_pay", members["dad"], 100, 0, 0)
    with pytest.raises(PermissionError):
        app.policy.authorize_payment(d, "JH-1", 999, "dad")
    with pytest.raises(PermissionError):
        app.policy.authorize_payment(d, "JH-1", 100, "mom")


def test_debit_is_idempotent(app, members):
    d = app.policy.evaluate_payment("auto_pay", members["dad"], 100, 0, 0)
    auth = app.policy.authorize_payment(d, "JH-1", 100, "dad")
    before = app.upi.remaining(app.mandate_id)
    t1 = app.upi.debit(app.mandate_id, auth)
    t2 = app.upi.debit(app.mandate_id, auth)
    assert t1["txn_id"] == t2["txn_id"] and t2["idempotent_replay"]
    assert app.upi.remaining(app.mandate_id) == before - 100
    assert t1["upi_ref"].isdigit() and len(t1["upi_ref"]) == 12


def test_submit_auto_pays_small_order(app, members):
    order = app.build_cart(members["didi"], DIDI_ITEMS)
    res = app.submit_order(members["didi"], order["order_id"])
    assert res["status"] == "paid" and res["payment"]["amount_inr"] == 48 + 40 + 95
    assert len(txns(app)) == 1
    events = [e["event"] for e in app.audit.events(order["order_id"])]
    assert events.index("policy_evaluated") < events.index("payment_captured")


def test_blocked_lines_are_not_paid_for(app, members):
    order = app.build_cart(members["teen"], [{"sku": "red-bull-energy-drink-250ml", "qty": 4},
                                             {"sku": "camlin-geometry-box-scholar-1pcs", "qty": 1}])
    res = app.submit_order(members["teen"], order["order_id"])
    assert res["status"] == "paid" and res["payable_inr"] == 120
    assert res["blocked_lines"][0]["policy_ids"] == ["teen-no-energy-drinks"]


def test_all_lines_blocked_no_payment(app, members):
    order = app.build_cart(members["dad"], [{"sku": "crunchy-bazaar-bikaneri-bhujia-family-pack-1kg", "qty": 10}])
    res = app.submit_order(members["dad"], order["order_id"])
    assert res["status"] == "denied" and txns(app) == []


def test_approval_flow(app, members):
    items = [{"sku": "amul-pure-ghee-1l", "qty": 1}, {"sku": "tata-sampann-rajma-chitra-1kg", "qty": 2}]
    order = app.build_cart(members["dad"], items)
    res = app.submit_order(members["dad"], order["order_id"])
    assert res["status"] == "pending_approval" and txns(app) == []
    assert any(n.to_member == "mom" for n in app.drain_outbox())
    # a non-admin cannot approve
    assert app.handle_approval(members["dad"], order["order_id"], "approve")["status"] == "error"
    assert app.get_order(order["order_id"])["status"] == "pending_approval"
    assert txns(app) == []


def test_cedar_rejects_non_admin_approver(app, members):
    d = app.policy.evaluate_payment("approved_pay", members["dad"], 1500, 0, 0, approver_role="adult")
    assert not d.allowed


def test_approval_by_admin_pays(app, members):
    order = app.build_cart(members["dad"], [{"sku": "amul-pure-ghee-1l", "qty": 2}])
    app.submit_order(members["dad"], order["order_id"])
    res = app.handle_approval(members["mom"], order["order_id"], "approve")
    assert res["status"] == "paid" and res["payment"]["amount_inr"] == 1280
    again = app.handle_approval(members["mom"], order["order_id"], "approve")
    assert again["status"] == "paid" and len(txns(app)) == 1


def test_rejection_does_not_pay(app, members):
    order = app.build_cart(members["dad"], [{"sku": "amul-pure-ghee-1l", "qty": 2}])
    app.submit_order(members["dad"], order["order_id"])
    assert app.handle_approval(members["mom"], order["order_id"], "reject")["status"] == "rejected"
    assert txns(app) == []


def test_mandate_exhausted_blocks_and_asks_admin(app, members):
    app.repo.put("mandate", app.mandate_id, {**app.upi.get(app.mandate_id), "month_spent_inr": 4900})
    order = app.build_cart(members["didi"], DIDI_ITEMS)
    res = app.submit_order(members["didi"], order["order_id"])
    assert res["status"] == "denied" and "mandate-monthly-cap" in res["deny"]["policy_ids"]
    out = app.drain_outbox()
    assert out and out[0].to_member == "mom" and "Top up" in out[0].buttons[0]["title"]
    assert txns(app) == []


def test_house_help_daily_cap_across_orders(app, members):
    didi = members["didi"]
    o1 = app.build_cart(didi, [{"sku": "aashirvaad-shudh-chakki-atta-5kg", "qty": 1}])
    assert app.submit_order(didi, o1["order_id"])["status"] == "paid"  # 289
    o2 = app.build_cart(didi, [{"sku": "aashirvaad-shudh-chakki-atta-5kg", "qty": 1}])
    res = app.submit_order(didi, o2["order_id"])
    assert res["status"] == "denied" and "house-help-daily-cap" in res["deny"]["policy_ids"]
