"""Cedar policy engine. The AI proposes; this module decides.

Two decision points:
  * line items:  Action::"purchase_item"  (Member -> Product)
  * payment:     Action::"auto_pay" | "request_approval" | "approved_pay"  (Member -> Mandate)

Every decision carries the determining policy ids and their human-readable reasons
(taken from @reason / @hinglish annotations in the .cedar files).
Only an allow on auto_pay / approved_pay produces a signed PaymentAuthorization,
which the UPI mandate service requires before it will debit.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cedarpy

from .config import POLICY_DIR
from .domain import Household, Member



def format_reason(text: str, hh: Household, extra: dict | None = None) -> str:
    """Fill the {threshold} / {cap} / {daily} / {admin} placeholders used in policy annotations
    (plus {for}, {allergens}, {vrat_until}, {caffeine_cap} for the dietary policies)."""
    md = hh.mandate
    for k, v in (("{threshold}", md.get("per_payment_approval_above_inr")), ("{cap}", md.get("monthly_cap_inr")),
                 ("{daily}", md.get("house_help_daily_cap_inr")), ("{admin}", hh.admin_label())):
        text = text.replace(k, str(v))
    for k, v in (extra or {}).items():
        text = text.replace("{" + k + "}", str(v))
    return text


# Dietary and allergy reasons come first: when a line is blocked for several reasons the safety one leads.
SAFETY_POLICIES = ("allergy", "diet-jain", "diet-vegan", "diet-vegetarian", "diet-eggetarian", "vrat-mode",
                   "caffeine-cap", "teen-caffeine-cap")


def _vrat_int(iso: str | None) -> int | None:
    try:
        return int(str(iso)[:10].replace("-", "")) if iso else None
    except ValueError:
        return None


def yyyymmdd(d) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def _today(today: int | None) -> int:
    """context.today: the caller's clock (orders pass it), else the real date in IST."""
    if today:
        return int(today)
    from datetime import datetime

    from .config import IST

    return yyyymmdd(datetime.now(IST).date())


@dataclass
class Decision:
    action: str
    allowed: bool
    policy_ids: list[str]
    reasons: list[str]
    reasons_hinglish: list[str]
    request: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PaymentAuthorization:
    order_id: str
    amount_inr: int
    action: str
    member_id: str
    policy_ids: tuple[str, ...]
    signature: str


class PolicyEngine:
    def __init__(self, household: Household, policy_dir: Path = POLICY_DIR,
                 custom_rules: list[dict] | None = None) -> None:
        """custom_rules: active household rules added from the console, each {id, title, cedar, ...}.

        They are evaluated together with the base policies (forbid always wins). A stored rule that
        no longer validates against the schema is skipped, never half-applied.
        """
        self.hh = household
        self.household_uid = {"type": "Household", "id": household.id}
        self.base_text = "\n".join(p.read_text() for p in sorted(policy_dir.glob("*.cedar")))
        self.schema_text = (policy_dir / "jhola.cedarschema").read_text()
        self.custom_rules = []
        texts = [self.base_text]
        for r in custom_rules or []:
            if not r.get("cedar"):
                continue
            res = cedarpy.validate_policies(self.base_text + "\n" + r["cedar"], self.schema_text)
            if res.validation_passed:
                texts.append(r["cedar"])
                self.custom_rules.append(r)
        self.policy_text = "\n".join(texts)
        self.policies = cedarpy.PolicySet.from_str(self.policy_text)
        self.schema = cedarpy.Schema.from_str(self.schema_text)
        pj = json.loads(cedarpy.policies_to_json_str(self.policy_text))["staticPolicies"]
        self.annotations = {pid: p.get("annotations", {}) for pid, p in pj.items()}
        titles = {f"custom-{r['id']}": r for r in self.custom_rules}
        for ann in self.annotations.values():
            rule = titles.get(ann.get("id", "").rsplit(".", 1)[0])
            if rule:
                ann.setdefault("reason", rule.get("title", ""))
                ann.setdefault("hinglish", rule.get("title_hinglish") or rule.get("title", ""))
        self._key = os.urandom(32)  # never leaves this object

    # ---------- validation ----------
    def validate(self) -> list[str]:
        res = cedarpy.validate_policies(self.policy_text, self.schema_text)
        return [] if res.validation_passed else [str(e) for e in res.errors]

    # ---------- entities ----------
    def _member_entity(self, m: Member) -> dict:
        attrs: dict = {"name": m.name, "role": m.role}
        if m.daily_cap_inr is not None:
            attrs["daily_cap_inr"] = int(m.daily_cap_inr)
        if m.order_cap_inr is not None:
            attrs["order_cap_inr"] = int(m.order_cap_inr)
        if m.allowed_categories:
            attrs["allowed_categories"] = [str(c) for c in m.allowed_categories]
        if m.delegation:  # expiry is NOT checked here: Cedar compares delegated_until with context.today
            attrs["delegated_cap_inr"] = int(m.delegation["cap_inr"])
            attrs["delegated_until"] = int(m.delegation["until"])
        attrs["diet_profile"] = str(m.diet_profile or "none")
        attrs["allergies"] = sorted({str(a) for a in m.allergies or []})
        vrat = _vrat_int(m.vrat_until)
        if vrat:  # expiry is decided by Cedar against context.today
            attrs["vrat_until"] = vrat
        if m.max_caffeine_mg is not None:
            attrs["max_caffeine_mg"] = int(m.max_caffeine_mg)
        return {"uid": {"type": "Member", "id": m.id}, "attrs": attrs, "parents": [self.household_uid]}

    def _base_entities(self, m: Member) -> list[dict]:
        return [{"uid": self.household_uid, "attrs": {}, "parents": []}, self._member_entity(m)]

    def _mandate_entity(self) -> dict:
        md = self.hh.mandate
        return {
            "uid": {"type": "Mandate", "id": md["mandate_id"]},
            "attrs": {
                "monthly_cap_inr": int(md["monthly_cap_inr"]),
                "approval_threshold_inr": int(md["per_payment_approval_above_inr"]),
                "house_help_daily_cap_inr": int(md["house_help_daily_cap_inr"]),
            },
            "parents": [],
        }

    @staticmethod
    def _product_entity(p: dict) -> dict:
        diet = p.get("diet") or {}
        is_food = bool(p.get("is_food", bool(diet)))
        return {
            "uid": {"type": "Product", "id": p["id"]},
            "attrs": {
                "name": p.get("name", ""),
                "brand": p["brand"],
                "category": p["category"],
                "tags": [str(t).lower() for t in p.get("tags", [])],
                "price_inr": int(p["price_inr"]),
                "seller_rating": {"__extn": {"fn": "decimal", "arg": f"{float(p['seller_rating']):.1f}"}},
                # Non-food (or a test product without diet data) is treated as fine for every diet.
                "is_food": is_food,
                "veg": bool(diet.get("veg", True)),
                "vegan": bool(diet.get("vegan", not is_food)),
                "jain_friendly": bool(diet.get("jain_friendly", not is_food)),
                "vrat_friendly": bool(diet.get("vrat_friendly", not is_food)),
                "eggetarian_only": bool(diet.get("eggetarian_only", False)),
                "allergens": sorted({str(a) for a in p.get("allergens") or []}),
                "contains": sorted({str(a) for a in p.get("contains") or []}),
                "caffeine_mg": int(p.get("caffeine_mg_per_serving") or 0),
            },
            "parents": [],
        }

    # ---------- core ----------
    def _decide(self, action: str, request: dict, entities: list[dict], extra: dict | None = None) -> Decision:
        res = cedarpy.is_authorized(request, self.policies, entities, self.schema)
        ids = [str(p) for p in res.diagnostics.reasons]
        errors = [str(e) for e in res.diagnostics.errors]
        named = [self.annotations.get(i, {}).get("id", i) for i in ids]
        order = sorted(range(len(named)), key=lambda i: (named[i] not in SAFETY_POLICIES, i))
        ids, named = [ids[i] for i in order], [named[i] for i in order]
        reasons = [format_reason(self.annotations.get(i, {}).get("reason", ""), self.hh, extra) for i in ids]
        hinglish = [format_reason(self.annotations.get(i, {}).get("hinglish", ""), self.hh, extra) for i in ids]
        allowed = res.allowed
        if not allowed and not ids:
            named, reasons, hinglish = ["default-deny"], ["No policy permits this."], ["Iski permission nahi hai."]
        return Decision(action, allowed, named, reasons, hinglish, request=request, errors=errors)

    def evaluate_line(self, member: Member, product: dict, quantity: int, today: int | None = None,
                      beneficiary: Member | None = None, order_caffeine_mg: int | None = None) -> Decision:
        """beneficiary: the member the item is FOR (default the buyer). Dietary policies check them.
        order_caffeine_mg: caffeine of every caffeinated line for that beneficiary (default: this line)."""
        b = beneficiary or member
        caffeine = int(product.get("caffeine_mg_per_serving") or 0)
        req = {
            "principal": {"type": "Member", "id": member.id},
            "action": {"type": "Action", "id": "purchase_item"},
            "resource": {"type": "Product", "id": product["id"]},
            "context": {"quantity": int(quantity), "line_total_inr": int(quantity * product["price_inr"]),
                        "today": _today(today), "beneficiary": {"__entity": {"type": "Member", "id": b.id}},
                        "order_caffeine_mg": int(order_caffeine_mg if order_caffeine_mg is not None
                                                 else caffeine * int(quantity))},
        }
        entities = self._base_entities(member) + [self._product_entity(product)]
        if b.id != member.id:
            entities.append(self._member_entity(b))
        hit = sorted({str(a) for a in product.get("allergens") or []} & {str(a) for a in b.allergies or []})
        extra = {"for": b.display, "allergens": ", ".join(a.replace("_", " ") for a in hit) or "an allergen",
                 "vrat_until": b.vrat_until or "", "caffeine_cap": b.max_caffeine_mg if b.max_caffeine_mg is not None else 100}
        return self._decide("purchase_item", req, entities, extra)

    def evaluate_payment(
        self,
        action: str,
        member: Member,
        order_total_inr: int,
        month_spent_inr: int,
        member_spent_today_inr: int,
        approver_role: str = "",
        today: int | None = None,
        member_spent_delegated_inr: int = 0,
    ) -> Decision:
        assert action in ("auto_pay", "request_approval", "approved_pay")
        req = {
            "principal": {"type": "Member", "id": member.id},
            "action": {"type": "Action", "id": action},
            "resource": {"type": "Mandate", "id": self.hh.mandate["mandate_id"]},
            "context": {
                "order_total_inr": int(order_total_inr),
                "month_spent_inr": int(month_spent_inr),
                "member_spent_today_inr": int(member_spent_today_inr),
                "approver_role": approver_role,
                "today": _today(today),
                "member_spent_delegated_inr": int(member_spent_delegated_inr),
            },
        }
        return self._decide(action, req, self._base_entities(member) + [self._mandate_entity()])

    # ---------- payment authorization tokens ----------
    def _sign(self, order_id: str, amount: int, action: str, member_id: str) -> str:
        msg = f"{order_id}|{amount}|{action}|{member_id}".encode()
        return hmac.new(self._key, msg, hashlib.sha256).hexdigest()

    def authorize_payment(self, decision: Decision, order_id: str, amount_inr: int, member_id: str) -> PaymentAuthorization:
        if not decision.allowed or decision.action not in ("auto_pay", "approved_pay"):
            raise PermissionError(f"Cedar did not allow payment ({decision.action}: {decision.policy_ids})")
        ctx = decision.request["context"]
        if ctx["order_total_inr"] != amount_inr or decision.request["principal"]["id"] != member_id:
            raise PermissionError("decision does not match the payment being authorized")
        sig = self._sign(order_id, amount_inr, decision.action, member_id)
        return PaymentAuthorization(order_id, amount_inr, decision.action, member_id, tuple(decision.policy_ids), sig)

    def verify(self, auth: PaymentAuthorization) -> bool:
        if not isinstance(auth, PaymentAuthorization):
            return False
        expected = self._sign(auth.order_id, auth.amount_inr, auth.action, auth.member_id)
        return hmac.compare_digest(expected, auth.signature)
