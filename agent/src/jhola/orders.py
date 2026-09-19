"""Order service: carts, Cedar-gated submission, approvals, payment.

The agent can only build carts and submit them. Payment happens exclusively inside
submit_order / approve after Cedar allows, via a signed PaymentAuthorization.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .audit import AuditLog
from .config import Clock
from .domain import DEMO_HOUSEHOLD_ID, Catalog, Household, Member, Pantry, Recipes, Resolver, describe
from .household import Directory
from .policy import Decision, PolicyEngine, yyyymmdd
from .store import Repository, ScopedRepository
from .upi import MandateService

DEFAULT_MONTH_SPENT_INR = 1850  # seeded usage so far this month (demo household only)

_catalog: Catalog | None = None


def shared_catalog() -> Catalog:
    global _catalog
    if _catalog is None:
        _catalog = Catalog.load()
    return _catalog


@dataclass
class Outbound:
    to_phone: str
    to_member: str
    text: str
    buttons: list[dict] = field(default_factory=list)
    kind: str = "info"  # info | approval | topup
    order_id: str | None = None


class Jhola:
    """Service container for ONE household. `repo` is the base repository; every read and write of
    household state goes through self.repo, which is scoped to household_id."""

    def __init__(self, repo: Repository, clock: Clock | None = None, month_spent_inr: int | None = None,
                 custom_rules: list[dict] | None = None, household_id: str | None = None) -> None:
        if isinstance(repo, ScopedRepository):
            household_id, repo = household_id or repo.household_id, repo.base
        self.household_id = household_id or DEMO_HOUSEHOLD_ID
        self.base = repo
        self.clock = clock or Clock()
        self.directory = Directory(repo, self.clock)
        if self.household_id == DEMO_HOUSEHOLD_ID:
            self.directory.ensure_demo()
        self.repo = self.directory.scoped(self.household_id)
        self.catalog = shared_catalog()
        self.hh = self.directory.load(self.household_id)
        stored = [r for r in self.repo.list("rules") if r.get("active")]
        self._attach_delegations(stored)
        if custom_rules is None:
            today = self.clock.today().isoformat()
            custom_rules = [r for r in stored if r.get("cedar") and (r.get("expires_on") or "9999") >= today]
        self.policy = PolicyEngine(self.hh, custom_rules=custom_rules)
        self.upi = MandateService(self.repo, self.policy, self.clock)
        self.audit = AuditLog(self.repo, self.clock)
        self.resolver = Resolver(self.catalog, self.hh)
        self.pantry = Pantry(self.catalog, self.hh)
        self.recipes = Recipes.load()
        self.outbox: list[Outbound] = []
        md = self.hh.mandate
        if self.repo.get("mandate", md["mandate_id"]) is None:
            seeded = DEFAULT_MONTH_SPENT_INR if self.hh.demo else 0
            self.upi.create_mandate(md["mandate_id"], md["payer_vpa"], md["monthly_cap_inr"],
                                    seeded if month_spent_inr is None else month_spent_inr)

    def _attach_delegations(self, rules: list[dict]) -> None:
        """Latest active delegation per member. Expiry is enforced by Cedar (context.today)."""
        for r in sorted((r for r in rules if r.get("kind") == "delegation"), key=lambda r: r.get("created_at", "")):
            m = self.hh.find(r.get("member_id", ""))
            if m:
                m.delegation = {"cap_inr": int(r["cap_inr"]), "starts_on": r["starts_on"],
                                "until": int(r["expires_on"].replace("-", "")), "rule_id": r["id"]}

    @property
    def mandate_id(self) -> str:
        return self.hh.mandate["mandate_id"]

    def notify(self, member: Member, text: str, buttons: list[dict] | None = None, order_id: str | None = None,
               kind: str = "info") -> None:
        self.outbox.append(Outbound(member.phone, member.id, text, buttons or [], kind, order_id))
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
            line = {"sku": p["id"], "label": describe(p), "category": p["category"], "qty": qty,
                    "unit_price_inr": p["price_inr"], "line_total_inr": qty * p["price_inr"]}
            if it.get("query"):  # the generic word the member used; lets the household learn its usual brand
                line.update(query=str(it["query"])[:60], source=str(it.get("source", "")))
            lines.append(line)
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

    def pending_approvals(self) -> list[dict]:
        return sorted((o for o in self.repo.list("orders") if o.get("status") == "pending_approval"),
                      key=lambda o: o.get("created_at", ""))

    def approval_text(self, order: dict) -> str:
        lines_txt = "\n".join(f"- {l['label']} x{l['qty']}" for l in order["lines"] if l.get("allowed"))
        why = "; ".join((order.get("approval_reasons") or {}).get("reasons", []))
        return (f"{self.hh.display_of(order['member_id'])} wants to order Rs {order['payable_inr']} "
                f"({order['order_id']}).\n{lines_txt}\nReason: {why}\nApprove karein?")

    # ---------- household summaries ----------
    def month_summary(self) -> dict:
        m = self.upi.get(self.mandate_id)
        month = m["month"]
        by_member: dict[str, int] = {}
        n = 0
        for o in self.repo.list("orders"):
            if o.get("status") == "paid" and o.get("paid_at", "")[:7] == month:
                by_member[o["member_id"]] = by_member.get(o["member_id"], 0) + o.get("paid_amount_inr", 0)
                n += 1
        return {"month": month, "budget_inr": m["monthly_cap_inr"], "spent_inr": m["month_spent_inr"],
                "remaining_inr": m["monthly_cap_inr"] - m["month_spent_inr"], "orders_paid": n,
                "by_member": [{"member": self.hh.display_of(k), "spent_inr": v}
                              for k, v in sorted(by_member.items(), key=lambda kv: -kv[1])],
                "pending_approvals": len(self.pending_approvals()), "payments_simulated": True}

    # ---------- spend ----------
    def member_spent_today(self, member_id: str) -> int:
        today = self.clock.today().isoformat()
        return sum(
            o.get("paid_amount_inr", 0) for o in self.repo.list("orders")
            if o["member_id"] == member_id and o["status"] == "paid" and o.get("paid_at", "")[:10] == today
        )

    def member_spent_since(self, member_id: str, since_iso_date: str) -> int:
        return sum(
            o.get("paid_amount_inr", 0) for o in self.repo.list("orders")
            if o["member_id"] == member_id and o["status"] == "paid" and o.get("paid_at", "")[:10] >= since_iso_date
        )

    def month_spent(self) -> int:
        return self.upi.get(self.mandate_id)["month_spent_inr"]

    def today_int(self) -> int:
        return yyyymmdd(self.clock.today())

    def _payment_decision(self, action: str, member: Member, total: int, approver_role: str = "") -> Decision:
        delegated = self.member_spent_since(member.id, member.delegation["starts_on"]) if member.delegation else 0
        return self.policy.evaluate_payment(
            action, member, total, self.month_spent(), self.member_spent_today(member.id), approver_role,
            today=self.today_int(), member_spent_delegated_inr=delegated,
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
                if l.get("query") and l.get("source") == "search":
                    # Paying for the default pick confirms it: next time this word means this product.
                    learned = self.hh.learn_preference(l["query"], l["sku"], 1, "order", member.id,
                                                       self.clock.now().isoformat())
                    if learned:
                        self.audit.log("preference_learned", order["order_id"], actor=member.id, **learned)
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
            d = self.policy.evaluate_line(member, self.catalog.get(l["sku"]), l["qty"], today=self.today_int())
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
            for admin in self.hh.admins():
                self.notify(
                    admin, self.approval_text(order),
                    buttons=[{"id": f"approve:{order_id}", "title": "Approve"},
                             {"id": f"reject:{order_id}", "title": "Reject"}],
                    order_id=order_id, kind="approval",
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
                    order_id=order_id, kind="topup",
                )
        return {**result, "status": "denied", "payment": None,
                "deny": {"policy_ids": d2.policy_ids, "reasons": d2.reasons, "reasons_hinglish": d2.reasons_hinglish}}

    # ---------- approvals ----------
    def handle_approval(self, admin: Member, order_id: str, decision: str) -> dict:
        order = self.get_order(order_id)
        if not order:
            return {"status": "error", "error": f"no such order {order_id}"}
        requester = self.hh.find(order["member_id"])
        if admin.role != "admin":
            self.audit.log("approval_rejected", order_id, actor=admin.id, reason="approver is not an admin")
            return {"status": "error", "order_id": order_id, "error": "only the admin can approve"}
        if order["status"] != "pending_approval":
            return {"status": order["status"], "order_id": order_id, "note": "not awaiting approval"}
        if requester is None:  # the member left the household while the order was waiting
            order["status"] = "cancelled"
            self.repo.put("orders", order_id, order)
            return {"status": "cancelled", "order_id": order_id, "note": "the member is no longer in the household"}
        self.audit.log("approval_response", order_id, actor=admin.id, decision=decision, admin_role=admin.role)
        if decision.lower() not in ("approve", "approved", "yes"):
            order["status"] = "rejected"
            self.repo.put("orders", order_id, order)
            self.notify(requester, f"{admin.display} ne order {order_id} (Rs {order['payable_inr']}) reject kar diya.", order_id=order_id)
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
