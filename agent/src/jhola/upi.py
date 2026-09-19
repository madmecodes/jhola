"""SIMULATED UPI AutoPay mandate service. No real money moves.

debit() only works with a PaymentAuthorization issued by the Cedar PolicyEngine,
and is idempotent per order id.
"""

from __future__ import annotations

import hashlib

from .config import Clock
from .policy import PaymentAuthorization, PolicyEngine
from .store import Repository

SIMULATED = True


class PaymentRejected(Exception):
    pass


class MandateService:
    def __init__(self, repo: Repository, policy: PolicyEngine, clock: Clock) -> None:
        self.repo = repo
        self.policy = policy
        self.clock = clock

    # ---------- mandate ----------
    def create_mandate(self, mandate_id: str, payer_vpa: str, monthly_cap_inr: int, month_spent_inr: int = 0) -> dict:
        m = {
            "mandate_id": mandate_id,
            "payer_vpa": payer_vpa,
            "monthly_cap_inr": monthly_cap_inr,
            "month": self.clock.now().strftime("%Y-%m"),
            "month_spent_inr": month_spent_inr,
            "status": "ACTIVE",
            "simulated": True,
        }
        self.repo.put("mandate", mandate_id, m)
        return m

    def get(self, mandate_id: str) -> dict:
        m = self.repo.get("mandate", mandate_id)
        if m is None:
            raise KeyError(mandate_id)
        month = self.clock.now().strftime("%Y-%m")
        if m["month"] != month:  # new month resets usage
            m.update(month=month, month_spent_inr=0)
            self.repo.put("mandate", mandate_id, m)
        return m

    def remaining(self, mandate_id: str) -> int:
        m = self.get(mandate_id)
        return m["monthly_cap_inr"] - m["month_spent_inr"]

    def top_up(self, mandate_id: str, new_cap_inr: int) -> dict:
        m = self.get(mandate_id)
        m["monthly_cap_inr"] = new_cap_inr
        self.repo.put("mandate", mandate_id, m)
        return m

    # ---------- debit ----------
    def _utr(self, order_id: str, amount_inr: int) -> str:
        # 12-digit UPI-style reference, stable per order (idempotent)
        n = int(hashlib.sha256(f"{order_id}|{amount_inr}".encode()).hexdigest(), 16) % 10**12
        return f"{n:012d}"

    def debit(self, mandate_id: str, auth: PaymentAuthorization) -> dict:
        if not self.policy.verify(auth):
            raise PaymentRejected("missing or invalid Cedar payment authorization")
        existing = self.repo.get("txns", auth.order_id)
        if existing:
            return {**existing, "idempotent_replay": True}
        m = self.get(mandate_id)
        if m["status"] != "ACTIVE":
            raise PaymentRejected("mandate not active")
        if m["month_spent_inr"] + auth.amount_inr > m["monthly_cap_inr"]:
            raise PaymentRejected("mandate cap exceeded")  # defence in depth; Cedar should already block
        m["month_spent_inr"] += auth.amount_inr
        self.repo.put("mandate", mandate_id, m)
        txn = {
            "txn_id": f"SIMUPI{self._utr(auth.order_id, auth.amount_inr)}",
            "upi_ref": self._utr(auth.order_id, auth.amount_inr),
            "order_id": auth.order_id,
            "amount_inr": auth.amount_inr,
            "mandate_id": mandate_id,
            "payer_vpa": m["payer_vpa"],
            "status": "SUCCESS",
            "authorized_by": list(auth.policy_ids),
            "at": self.clock.now().isoformat(),
            "simulated": True,
        }
        self.repo.put("txns", auth.order_id, txn)
        return txn
