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

HOUSEHOLD_UID = {"type": "Household", "id": "gupta"}


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
        self.base_text = "\n".join(p.read_text() for p in sorted(policy_dir.glob("*.cedar")))
        self.schema_text = (policy_dir / "jhola.cedarschema").read_text()
        self.custom_rules = []
        texts = [self.base_text]
        for r in custom_rules or []:
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
        return {
            "uid": {"type": "Member", "id": m.id},
            "attrs": {"name": m.name, "role": m.role},
            "parents": [HOUSEHOLD_UID],
        }

    def _base_entities(self, m: Member) -> list[dict]:
        return [{"uid": HOUSEHOLD_UID, "attrs": {}, "parents": []}, self._member_entity(m)]

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
        return {
            "uid": {"type": "Product", "id": p["id"]},
            "attrs": {
                "name": p.get("name", ""),
                "brand": p["brand"],
                "category": p["category"],
                "tags": [str(t).lower() for t in p.get("tags", [])],
                "price_inr": int(p["price_inr"]),
                "seller_rating": {"__extn": {"fn": "decimal", "arg": f"{float(p['seller_rating']):.1f}"}},
            },
            "parents": [],
        }

    # ---------- core ----------
    def _decide(self, action: str, request: dict, entities: list[dict]) -> Decision:
        res = cedarpy.is_authorized(request, self.policies, entities, self.schema)
        ids = [str(p) for p in res.diagnostics.reasons]
        errors = [str(e) for e in res.diagnostics.errors]
        named = [self.annotations.get(i, {}).get("id", i) for i in ids]
        reasons = [self.annotations.get(i, {}).get("reason", "") for i in ids]
        hinglish = [self.annotations.get(i, {}).get("hinglish", "") for i in ids]
        allowed = res.allowed
        if not allowed and not ids:
            named, reasons, hinglish = ["default-deny"], ["No policy permits this."], ["Iski permission nahi hai."]
        return Decision(action, allowed, named, reasons, hinglish, request=request, errors=errors)

    def evaluate_line(self, member: Member, product: dict, quantity: int) -> Decision:
        req = {
            "principal": {"type": "Member", "id": member.id},
            "action": {"type": "Action", "id": "purchase_item"},
            "resource": {"type": "Product", "id": product["id"]},
            "context": {"quantity": int(quantity), "line_total_inr": int(quantity * product["price_inr"])},
        }
        return self._decide("purchase_item", req, self._base_entities(member) + [self._product_entity(product)])

    def evaluate_payment(
        self,
        action: str,
        member: Member,
        order_total_inr: int,
        month_spent_inr: int,
        member_spent_today_inr: int,
        approver_role: str = "",
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
