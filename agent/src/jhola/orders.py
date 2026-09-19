"""Order service: carts, Cedar-gated submission, approvals, payment.

The agent can only build carts and submit them. Payment happens exclusively inside
submit_order / approve after Cedar allows, via a signed PaymentAuthorization.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .audit import AuditLog
from .config import Clock
from .domain import Catalog, Household, Member, Pantry, Recipes, Resolver, describe
from .policy import Decision, PolicyEngine
from .store import Repository
from .upi import MandateService

DEFAULT_MONTH_SPENT_INR = 1850  # seeded usage so far this month (demo)


@dataclass
class Outbound:
    to_phone: str
    to_member: str
    text: str
    buttons: list[dict] = field(default_factory=list)


class Jhola:
    """Service container. One per household."""

    def __init__(self, repo: Repository, clock: Clock | None = None, month_spent_inr: int | None = None,
                 custom_rules: list[dict] | None = None) -> None:
        self.repo = repo
        self.clock = clock or Clock()
        self.catalog = Catalog.load()
        self.hh = Household.load(repo)
        if custom_rules is None:
            custom_rules = [r for r in repo.list("rules") if r.get("active")]
        self.policy = PolicyEngine(self.hh, custom_rules=custom_rules)
        self.upi = MandateService(repo, self.policy, self.clock)
        self.audit = AuditLog(repo, self.clock)
        self.resolver = Resolver(self.catalog, self.hh)
        self.pantry = Pantry(self.catalog, self.hh)
        self.recipes = Recipes.load()
        self.outbox: list[Outbound] = []
        md = self.hh.mandate
        if repo.get("mandate", md["mandate_id"]) is None:
            self.upi.create_mandate(
                md["mandate_id"], md["payer_vpa"], md["monthly_cap_inr"],
                DEFAULT_MONTH_SPENT_INR if month_spent_inr is None else month_spent_inr,
            )

    @property
    def mandate_id(self) -> str:
        return self.hh.mandate["mandate_id"]

    def notify(self, member: Member, text: str, buttons: list[dict] | None = None, order_id: str | None = None) -> None:
        self.outbox.append(Outbound(member.phone, member.id, text, buttons or []))
        self.audit.log("notification_sent", order_id, actor="jhola", to=member.id, text=text, buttons=buttons or [])

    def drain_outbox(self) -> list[Outbound]:
        out, self.outbox = self.outbox, []
        return out

    # ---------- carts ----------
    def _new_order_id(self) -> str:
        n = self.repo.next_seq("orders", self._highest_order_number)
        return f"JH-{self.clock.now():%Y%m%d}-{n:04d}"

    def _highest_order_number(self) -> int:
        """Seed for the order counter: never reuse an id still referenced by orders or the audit log
        (a demo reset clears orders but keeps the audit trail)."""
        ids = [o.get("order_id") for o in self.repo.list("orders")]
        ids += [e.get("order_id") for e in self.repo.list("audit")]
        nums = [int(i.rsplit("-", 1)[1]) for i in ids if i and i.startswith("JH-") and i.rsplit("-", 1)[1].isdigit()]
        return max(nums, default=0)

    def build_cart(self, member: Member, items: list[dict], note: str = "", meta: dict | None = None) -> dict:
        lines, problems = [], []
        for it in items:
            p = self.catalog.get(str(it.get("sku", "")))
            qty = int(it.get("qty", 1) or 1)
            if not p:
                problems.append(f"unknown sku {it.get('sku')}")
                continue
            lines.append({
                "sku": p["id"], "label": describe(p), "category": p["category"], "qty": qty,
                "unit_price_inr": p["price_inr"], "line_total_inr": qty * p["price_inr"],
            })
        order = {
            "order_id": self._new_order_id(),
            "member_id": member.id,
            "status": "draft",
            "created_at": self.clock.now().isoformat(),
            "lines": lines,
            "total_inr": sum(l["line_total_inr"] for l in lines),
            "note": note,
            "channel": "whatsapp",
            "input_type": "text",
            **(meta or {}),
        }
        self.repo.put("orders", order["order_id"], order)
        self.audit.log("cart_built", order["order_id"], actor=member.id, lines=lines,
                       total_inr=order["total_inr"], problems=problems)
        return {**order, "problems": problems}

    def get_order(self, order_id: str) -> dict | None:
        return self.repo.get("orders", order_id)

    # ---------- spend ----------
    def member_spent_today(self, member_id: str) -> int:
        today = self.clock.today().isoformat()
        return sum(
            o.get("paid_amount_inr", 0) for o in self.repo.list("orders")
            if o["member_id"] == member_id and o["status"] == "paid" and o.get("paid_at", "")[:10] == today
        )

    def month_spent(self) -> int:
        return self.upi.get(self.mandate_id)["month_spent_inr"]

    def _payment_decision(self, action: str, member: Member, total: int, approver_role: str = "") -> Decision:
        return self.policy.evaluate_payment(
            action, member, total, self.month_spent(), self.member_spent_today(member.id), approver_role
        )

    def _log_decision(self, order_id: str, d: Decision, **extra) -> None:
        self.audit.log(
            "policy_evaluated", order_id, actor="cedar", action=d.action, allowed=d.allowed,
            policy_ids=d.policy_ids, reasons=d.reasons, cedar_request=d.request, errors=d.errors, **extra,
        )

    def _pay(self, order: dict, member: Member, d: Decision) -> dict:
        auth = self.policy.authorize_payment(d, order["order_id"], order["payable_inr"], member.id)
        txn = self.upi.debit(self.mandate_id, auth)
        order.update(status="paid", paid_amount_inr=txn["amount_inr"], paid_at=self.clock.now().isoformat(),
                     txn=txn)
        self.repo.put("orders", order["order_id"], order)
        self.audit.log("payment_captured", order["order_id"], actor="upi-sim", txn=txn,
                       mandate_remaining_inr=self.upi.remaining(self.mandate_id))
        for l in order["lines"]:
            if l.get("allowed"):
                self.hh.record_purchase(self.clock.today(), l["sku"], l["qty"], member.id, order["order_id"])
        return txn

    # ---------- submission ----------
    def submit_order(self, member: Member, order_id: str) -> dict:
        order = self.get_order(order_id)
        if not order:
            return {"status": "error", "error": f"no such order {order_id}"}
        if order["member_id"] != member.id:
            return {"status": "error", "error": "order belongs to another member"}
        if order["status"] != "draft":
            return {"status": order["status"], "order_id": order_id, "note": "already submitted"}

        # 1. line items
        blocked = []
        for l in order["lines"]:
            d = self.policy.evaluate_line(member, self.catalog.get(l["sku"]), l["qty"])
            self._log_decision(order_id, d, sku=l["sku"], qty=l["qty"])
            l.update(allowed=d.allowed, policy_ids=d.policy_ids, reasons=d.reasons, reasons_hinglish=d.reasons_hinglish)
            if not d.allowed:
                blocked.append(l)
        allowed_lines = [l for l in order["lines"] if l["allowed"]]
        order["payable_inr"] = sum(l["line_total_inr"] for l in allowed_lines)
        order["blocked_lines"] = [
            {"label": l["label"], "qty": l["qty"], "policy_ids": l["policy_ids"], "reasons": l["reasons"],
             "reasons_hinglish": l["reasons_hinglish"]} for l in blocked
        ]
        result = {"order_id": order_id, "allowed_lines": [{"label": l["label"], "qty": l["qty"],
                  "line_total_inr": l["line_total_inr"]} for l in allowed_lines],
                  "blocked_lines": order["blocked_lines"], "payable_inr": order["payable_inr"]}
        if not allowed_lines:
            order["status"] = "denied"
            self.repo.put("orders", order_id, order)
            self.audit.log("order_denied", order_id, actor="cedar", stage="items")
            return {**result, "status": "denied", "payment": None}

        # 2. payment: auto_pay -> request_approval -> deny
        total = order["payable_inr"]
        d = self._payment_decision("auto_pay", member, total)
        self._log_decision(order_id, d)
        if d.allowed:
            txn = self._pay(order, member, d)
            return {**result, "status": "paid", "payment": {"txn_id": txn["txn_id"], "upi_ref": txn["upi_ref"],
                    "amount_inr": txn["amount_inr"], "simulated": True},
                    "mandate_remaining_inr": self.upi.remaining(self.mandate_id)}
        auto_reasons = {"policy_ids": d.policy_ids, "reasons": d.reasons, "reasons_hinglish": d.reasons_hinglish}

        d2 = self._payment_decision("request_approval", member, total)
        self._log_decision(order_id, d2)
        if d2.allowed:
            order.update(status="pending_approval", approval_reasons=auto_reasons)
            self.repo.put("orders", order_id, order)
            self.audit.log("approval_requested", order_id, actor=member.id, amount_inr=total, why=auto_reasons)
            lines_txt = "\n".join(f"- {l['label']} x{l['qty']}" for l in allowed_lines)
            for admin in self.hh.admins():
                self.notify(
                    admin,
                    f"{member.display} wants to order Rs {total} ({order_id}).\n{lines_txt}\n"
                    f"Reason: {'; '.join(d.reasons)}\nApprove karein?",
                    buttons=[{"id": f"approve:{order_id}", "title": "Approve"},
                             {"id": f"reject:{order_id}", "title": "Reject"}],
                    order_id=order_id,
                )
            return {**result, "status": "pending_approval", "payment": None, "needs_approval_because": auto_reasons}

        order.update(status="denied", deny_reasons={"policy_ids": d2.policy_ids, "reasons": d2.reasons})
        self.repo.put("orders", order_id, order)
        self.audit.log("order_denied", order_id, actor="cedar", stage="payment", policy_ids=d2.policy_ids)
        if "mandate-monthly-cap" in d2.policy_ids:
            rem = self.upi.remaining(self.mandate_id)
            for admin in self.hh.admins():
                self.notify(
                    admin,
                    f"{member.display} ka order Rs {total} ({order_id}) ruk gaya: UPI AutoPay mandate mein sirf "
                    f"Rs {rem} bacha hai. Limit badhani ho to Top up dabaiye.",
                    buttons=[{"id": f"topup:{self.mandate_id}", "title": "Top up mandate"}],
                    order_id=order_id,
                )
        return {**result, "status": "denied", "payment": None,
                "deny": {"policy_ids": d2.policy_ids, "reasons": d2.reasons, "reasons_hinglish": d2.reasons_hinglish}}

    # ---------- approvals ----------
    def handle_approval(self, admin: Member, order_id: str, decision: str) -> dict:
        order = self.get_order(order_id)
        if not order:
            return {"status": "error", "error": f"no such order {order_id}"}
        requester = self.hh.member(order["member_id"])
        if admin.role != "admin":
            self.audit.log("approval_rejected", order_id, actor=admin.id, reason="approver is not an admin")
            return {"status": "error", "order_id": order_id, "error": "only the admin can approve"}
        if order["status"] != "pending_approval":
            return {"status": order["status"], "order_id": order_id, "note": "not awaiting approval"}
        self.audit.log("approval_response", order_id, actor=admin.id, decision=decision, admin_role=admin.role)
        if decision.lower() not in ("approve", "approved", "yes"):
            order["status"] = "rejected"
            self.repo.put("orders", order_id, order)
            self.notify(requester, f"Mom ne order {order_id} (Rs {order['payable_inr']}) reject kar diya.", order_id=order_id)
            return {"status": "rejected", "order_id": order_id}
        d = self._payment_decision("approved_pay", requester, order["payable_inr"], approver_role=admin.role)
        self._log_decision(order_id, d, approver=admin.id)
        if not d.allowed:
            order["status"] = "denied"
            self.repo.put("orders", order_id, order)
            return {"status": "denied", "order_id": order_id, "policy_ids": d.policy_ids, "reasons": d.reasons}
        txn = self._pay(order, requester, d)
        self.notify(requester, f"{admin.display} ne approve kar diya. Rs {txn['amount_inr']} paid "
                    f"(UPI ref {txn['upi_ref']}, SIMULATED). Order {order_id} aa raha hai.", order_id=order_id)
        return {"status": "paid", "order_id": order_id, "payment": {"txn_id": txn["txn_id"], "upi_ref": txn["upi_ref"],
                "amount_inr": txn["amount_inr"], "simulated": True},
                "mandate_remaining_inr": self.upi.remaining(self.mandate_id)}
