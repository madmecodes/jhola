"""Cedar policy tests: line items and payment decisions."""

import pytest


def line(app, m, sku, qty=1):
    return app.policy.evaluate_line(m, app.catalog.get(sku), qty)


def pay(app, action, m, total, month_spent=0, today=0, approver=""):
    return app.policy.evaluate_payment(action, m, total, month_spent, today, approver)


def test_policies_validate_against_schema(app):
    assert app.policy.validate() == []


def test_every_policy_has_id_and_reasons(app):
    for pid, ann in app.policy.annotations.items():
        assert ann.get("id") and ann.get("reason") and ann.get("hinglish"), pid


# ---------- teen ----------
def test_teen_energy_drink_forbidden(app, members):
    for sku in ["red-bull-energy-drink-250ml", "monster-energy-drink-original-350ml"]:
        d = line(app, members["teen"], sku)
        assert not d.allowed
        assert "teen-no-energy-drinks" in d.policy_ids
        assert d.reasons and d.reasons_hinglish


def test_teen_stationery_and_snacks_allowed(app, members):
    assert line(app, members["teen"], "camlin-geometry-box-scholar-1pcs").allowed
    assert line(app, members["teen"], "parle-parle-g-original-250g").allowed


def test_teen_other_categories_denied(app, members):
    d = line(app, members["teen"], "aashirvaad-shudh-chakki-atta-5kg")
    assert not d.allowed and "teen-outside-scope" in d.policy_ids


# ---------- house help ----------
@pytest.mark.parametrize("sku", ["aashirvaad-shudh-chakki-atta-5kg", "nandini-toned-milk-500ml",
                                 "freshfarm-onion-1kg", "freshfarm-banana-robusta-6pcs",
                                 "vim-dishwash-bar-3-pack-3pcs"])
def test_house_help_allowed_categories(app, members, sku):
    assert line(app, members["didi"], sku).allowed


@pytest.mark.parametrize("sku", ["red-bull-energy-drink-250ml", "parle-parle-g-gold-1kg",
                                 "classmate-notebook-single-line-172-pages-1pcs", "cycle-3-in-1-agarbatti-1pcs"])
def test_house_help_other_categories_denied(app, members, sku):
    d = line(app, members["didi"], sku)
    assert not d.allowed and "house-help-outside-scope" in d.policy_ids


def test_house_help_daily_cap(app, members):
    didi = members["didi"]
    assert pay(app, "auto_pay", didi, 342).allowed
    d = pay(app, "auto_pay", didi, 200, today=342)
    assert not d.allowed and "house-help-daily-cap" in d.policy_ids
    assert not pay(app, "request_approval", didi, 200, today=342).allowed
    assert not pay(app, "approved_pay", didi, 200, today=342, approver="admin").allowed
    assert pay(app, "auto_pay", didi, 158, today=342).allowed  # exactly 500


# ---------- everyone ----------
def test_low_rated_seller_denied_even_for_admin(app, members):
    for who in ["mom", "dad", "didi"]:
        d = line(app, members[who], "local-mill-sona-masoori-rice-5kg")
        assert not d.allowed and "min-seller-rating" in d.policy_ids


def test_rating_boundary_4_0_allowed(app, members):
    assert line(app, members["dad"], "patanjali-cow-ghee-1l").allowed  # rating 4.0


def test_quantity_limit_non_admin(app, members):
    assert line(app, members["dad"], "freshfarm-onion-1kg", 5).allowed
    d = line(app, members["dad"], "freshfarm-onion-1kg", 6)
    assert not d.allowed and "max-qty-per-line" in d.policy_ids
    d = line(app, members["didi"], "nandini-toned-milk-500ml", 10)
    assert not d.allowed and "max-qty-per-line" in d.policy_ids


def test_quantity_limit_admin_exempt(app, members):
    assert line(app, members["mom"], "nandini-toned-milk-500ml", 14).allowed


# ---------- payments ----------
def test_auto_pay_under_threshold(app, members):
    d = pay(app, "auto_pay", members["dad"], 1000, month_spent=1850)
    assert d.allowed and d.policy_ids == ["mandate-auto-pay"]


def test_above_threshold_needs_approval(app, members):
    d = pay(app, "auto_pay", members["dad"], 1179, month_spent=1850)
    assert not d.allowed and d.policy_ids == ["approval-above-threshold"]
    assert pay(app, "request_approval", members["dad"], 1179, month_spent=1850).allowed
    assert not pay(app, "approved_pay", members["dad"], 1179, month_spent=1850).allowed  # no admin yet
    assert pay(app, "approved_pay", members["dad"], 1179, month_spent=1850, approver="admin").allowed


def test_admin_own_order_above_threshold_auto_pays(app, members):
    assert pay(app, "auto_pay", members["mom"], 1500).allowed


def test_mandate_cap_blocks_everything(app, members):
    for action, approver in [("auto_pay", ""), ("request_approval", ""), ("approved_pay", "admin")]:
        for who in ["mom", "dad", "didi"]:
            d = pay(app, action, members[who], 342, month_spent=4800, approver=approver)
            assert not d.allowed and "mandate-monthly-cap" in d.policy_ids, (action, who)
    assert pay(app, "auto_pay", members["mom"], 200, month_spent=4800).allowed  # exactly the cap
