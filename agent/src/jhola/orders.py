"""Order service: carts, Cedar-gated submission, approvals, payment.

The agent can only build carts and submit them. Payment happens exclusively inside
submit_order / approve after Cedar allows, via a signed PaymentAuthorization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .audit import AuditLog
from .config import Clock
from .domain import DEMO_HOUSEHOLD_ID, Catalog, Household, Member, Pantry, Recipes, Resolver, describe
from .household import Directory
from .policy import Decision, PolicyEngine, yyyymmdd
from .store import Repository, ScopedRepository
from .upi import MandateService

DEFAULT_MONTH_SPENT_INR = 0  # the demo mandate starts empty so used always equals the orders on screen
DUPLICATE_WINDOW_MIN = 60  # "Dad ne 20 min pehle doodh order kiya hai": look back this long

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

    def beneficiary(self, member: Member, ref: str | None) -> Member:
        """The member an item is FOR: "Dadi ke liye" -> Dadi; unknown or empty -> the buyer."""
        if not ref or str(ref).strip().lower() in ("self", "me", "myself", member.id):
            return member
        return self.hh.find_by_name(str(ref)) or member

    def build_cart(self, member: Member, items: list[dict], note: str = "", meta: dict | None = None,
                   for_member: str | None = None) -> dict:
        lines, problems = [], []
        default_for = self.beneficiary(member, for_member)
        for it in items:
            p = self.catalog.get(str(it.get("sku", "")))
            qty = int(it.get("qty", 1) or 1)
            if not p:
                problems.append(f"unknown sku {it.get('sku')}")
                continue
            b = self.beneficiary(member, it.get("for_member")) if it.get("for_member") else default_for
            line = {"sku": p["id"], "label": describe(p), "category": p["category"], "qty": qty,
                    "unit_price_inr": p["price_inr"], "line_total_inr": qty * p["price_inr"]}
            if b.id != member.id:
                line["for_member"] = b.id
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
        dups = self.recent_family_orders(member, lines)
        if dups:
            order["duplicates"] = dups
        self.repo.put("orders", order["order_id"], order)
        nudges = self.pantry_nudges(lines)
        self.audit.log("cart_built", order["order_id"], actor=member.id, lines=lines,
                       total_inr=order["total_inr"], problems=problems, duplicates=dups, pantry_nudges=nudges)
        out = {**order, "problems": problems}
        if nudges:
            out["probably_at_home"] = nudges
        if dups:
            out["recently_ordered_by_family"] = dups
            out["note_for_assistant"] = ("submit_order will ask the member Yes / No about these before paying; "
                                         "do not ask yourself, just call submit_order.")
        return out

    # ---------- family cart merge and pantry nudges ----------
    @staticmethod
    def _same_item(p: dict, q: dict) -> bool:
        return p["id"] == q["id"] or (p["category"] == q["category"] and bool(set(p["tags"][:2]) & set(q["tags"][:2])))

    def recent_family_orders(self, member: Member, lines: list[dict]) -> list[dict]:
        """Lines another member ordered in the last hour (still pending, or paid within the hour)."""
        now = self.clock.now()
        out = []
        for o in self.repo.list("orders"):
            if o.get("member_id") == member.id or o.get("status") not in ("pending_approval", "paid"):
                continue
            when = o.get("paid_at") if o.get("status") == "paid" else o.get("created_at")
            try:
                age = (now - datetime.fromisoformat(when)).total_seconds() / 60
            except (TypeError, ValueError):
                continue
            if not 0 <= age <= DUPLICATE_WINDOW_MIN:
                continue
            for ol in o.get("lines", []):
                if ol.get("allowed") is False:
                    continue
                q = self.catalog.get(ol["sku"])
                for l in lines:
                    p = self.catalog.get(l["sku"])
                    if p and q and self._same_item(p, q):
                        out.append({"sku": l["sku"], "item": l["label"].split(" (Rs")[0], "by": self.hh.display_of(o["member_id"]),
                                    "minutes_ago": int(age), "status": o["status"], "order_id": o["order_id"],
                                    "qty": ol["qty"]})
        return out

    def duplicate_text(self, order: dict) -> str:
        parts = []
        for d in order.get("duplicates", []):
            st = "paid" if d["status"] == "paid" else "approval pending"
            parts.append(f"{d['by']} ne {d['minutes_ago']} min pehle {d['item']} x{d['qty']} order kiya hai ({st}).")
        return " ".join(dict.fromkeys(parts)) + " Phir bhi chahiye?"

    def pantry_nudges(self, lines: list[dict]) -> list[dict]:
        """Items in the cart that purchase history says are probably still at home (non-blocking)."""
        today = self.clock.today()
        out = []
        for l in lines:
            p = self.catalog.get(l["sku"])
            if not p or not p.get("is_food", True):
                continue
            s = self.pantry.status_for_sku(l["sku"], today)
            if s.get("in_pantry"):
                out.append({"sku": l["sku"], "item": l["label"].split(" (Rs")[0], "last_bought": s["last_bought"],
                            "expected_run_out": s["expected_run_out"], "by": s.get("by", "")})
        return out

    def get_order(self, order_id: str) -> dict | None:
        return self.repo.get("orders", order_id)

    def pending_approvals(self) -> list[dict]:
        return sorted((o for o in self.repo.list("orders") if o.get("status") == "pending_approval"),
                      key=lambda o: o.get("created_at", ""))

    def drop_duplicates(self, member: Member, order_id: str) -> dict:
        """"No" to the duplicate question: remove the lines the family already ordered, submit the rest."""
        order = self.get_order(order_id)
        if not order or order["member_id"] != member.id or order["status"] != "draft":
            return {"status": "error", "error": "order is not a draft of this member"}
        dup_skus = {d["sku"] for d in order.get("duplicates", [])}
        kept = [l for l in order["lines"] if l["sku"] not in dup_skus]
        self.audit.log("duplicates_dropped", order_id, actor=member.id, dropped=sorted(dup_skus))
        if not kept:
            order.update(status="cancelled", duplicates_confirmed=True)
            self.repo.put("orders", order_id, order)
            return {"status": "cancelled", "order_id": order_id, "note": "nothing left to order"}
        order.update(lines=kept, total_inr=sum(l["line_total_inr"] for l in kept), duplicates_confirmed=True)
        self.repo.put("orders", order_id, order)
        return self.submit_order(member, order_id, confirm_duplicates=True)

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
    def line_beneficiary(self, member: Member, line: dict) -> Member:
        return self.hh.find(line.get("for_member", "")) or member if line.get("for_member") else member

    def order_caffeine(self, order: dict, beneficiary_id: str) -> int:
        total = 0
        for l in order["lines"]:
            if (l.get("for_member") or order["member_id"]) == beneficiary_id:
                p = self.catalog.get(l["sku"]) or {}
                total += int(p.get("caffeine_mg_per_serving") or 0) * int(l["qty"])
        return total

    def check_line(self, member: Member, product: dict, qty: int, for_member: str | None = None) -> dict:
        """Dry Cedar check of one line (no order): the same decision submit_order would make, plus the
        closest allowed substitute when it is blocked. Used by resolve_item so the model can offer the
        substitute before building a cart."""
        b = self.beneficiary(member, for_member)
        d = self.policy.evaluate_line(member, product, qty, today=self.today_int(), beneficiary=b)
        out = {"allowed": d.allowed, "for": b.display}
        if not d.allowed:
            out.update(policy_ids=d.policy_ids, reasons=d.reasons, reasons_hinglish=d.reasons_hinglish)
            sub = self.compliant_substitute(member, b, product, qty)
            if sub:
                out["suggested_substitute"] = sub
        return out

    def compliant_substitute(self, member: Member, beneficiary: Member, product: dict, qty: int = 1) -> dict | None:
        """Closest in-stock product that Cedar ALLOWS for this buyer and beneficiary: same category and
        overlapping tags first (Jain mixture for a mixture), otherwise anything sharing a tag."""
        base_tags = [t for t in product["tags"] if t not in ("jain", "vrat", "farali")][:3]
        cands = []
        for it in self.catalog.items:
            if it["id"] == product["id"] or not it["in_stock"] or it["seller_rating"] < 4.0:
                continue
            overlap = len(set(it["tags"]) & set(base_tags))
            if not overlap:
                continue
            cands.append((0 if it["category"] == product["category"] else 1, -overlap,
                          abs(it["price_inr"] - product["price_inr"]), it["id"], it))
        for _, _, _, _, it in sorted(cands)[:12]:
            d = self.policy.evaluate_line(member, it, min(qty, 5), today=self.today_int(), beneficiary=beneficiary)
            if d.allowed:
                return {"sku": it["id"], "label": describe(it), "why": " / ".join(
                    t for t in ("jain" if (it.get("diet") or {}).get("jain_friendly") else "",
                                "vrat" if (it.get("diet") or {}).get("vrat_friendly") else "",
                                "no added sugar" if "added_sugar" not in (it.get("contains") or []) else "") if t)}
        return None

    def submit_order(self, member: Member, order_id: str, confirm_duplicates: bool = False) -> dict:
        order = self.get_order(order_id)
        if not order:
            return {"status": "error", "error": f"no such order {order_id}"}
        if order["member_id"] != member.id:
            return {"status": "error", "error": "order belongs to another member"}
        if order["status"] != "draft":
            return {"status": order["status"], "order_id": order_id, "note": "already submitted"}
        if order.get("duplicates") and not confirm_duplicates and not order.get("duplicates_confirmed"):
            # Family cart merge: someone else just ordered the same thing. Ask before paying (code writes
            # the question and the Yes / No buttons; the model only relays it).
            self.audit.log("duplicate_check", order_id, actor="jhola", duplicates=order["duplicates"])
            return {"order_id": order_id, "status": "needs_confirmation", "reason": "recently_ordered_by_family",
                    "question": self.duplicate_text(order), "duplicates": order["duplicates"],
                    "note": "The member gets Yes / No buttons. Do NOT ask again; just relay the question."}

        # 1. line items (dietary rules apply to the member each line is FOR)
        blocked = []
        for l in order["lines"]:
            b = self.line_beneficiary(member, l)
            p = self.catalog.get(l["sku"])
            d = self.policy.evaluate_line(member, p, l["qty"], today=self.today_int(), beneficiary=b,
                                          order_caffeine_mg=self.order_caffeine(order, b.id))
            self._log_decision(order_id, d, sku=l["sku"], qty=l["qty"], for_member=b.id)
            l.update(allowed=d.allowed, policy_ids=d.policy_ids, reasons=d.reasons, reasons_hinglish=d.reasons_hinglish)
            if not d.allowed:
                sub = self.compliant_substitute(member, b, p, l["qty"])
                if sub:
                    l["suggested_substitute"] = sub
                blocked.append(l)
        allowed_lines = [l for l in order["lines"] if l["allowed"]]
        order["payable_inr"] = sum(l["line_total_inr"] for l in allowed_lines)
        order["blocked_lines"] = [
            {"label": l["label"], "qty": l["qty"], "policy_ids": l["policy_ids"], "reasons": l["reasons"],
             "reasons_hinglish": l["reasons_hinglish"], "for": self.hh.display_of(l.get("for_member") or member.id),
             **({"suggested_substitute": l["suggested_substitute"]} if l.get("suggested_substitute") else {})}
            for l in blocked
        ]
        result = {"order_id": order_id, "allowed_lines": [{"label": l["label"], "qty": l["qty"],
                  "line_total_inr": l["line_total_inr"]} for l in allowed_lines],
                  "blocked_lines": order["blocked_lines"], "payable_inr": order["payable_inr"]}
        if not allowed_lines:
            order["status"] = "denied"
            self.repo.put("orders", order_id, order)
            self.audit.log("order_denied", order_id, actor="cedar", stage="items")
            return {**result, "status": "denied", "payment": None,
                    "note": "Offer the suggested_substitute (if any) in one line and ask if they want it."}

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
