"""Tenancy: the household directory.

Identity is the sender's WhatsApp phone number. The global collection "phones" maps an E.164 phone to
(household_id, member_id); "households" holds each household's profile and mandate settings. Members,
learned preferences and everything else live in the household's own partitions (see store.py).

The seeded Gupta family (household_id demo-gupta) is created on first use so the scenarios, the
console and the red team keep working. Phones flagged demo=true may use the /as persona switch.
"""

from __future__ import annotations

import re
import uuid

from . import config
from .config import Clock
from .domain import DEMO_HOUSEHOLD_ID, GROCERIES, Household, Member, demo_household_raw
from .phones import to_e164
from .store import Repository, ScopedRepository

DEFAULT_BUDGET_INR = 5000
DEFAULT_THRESHOLD_INR = 1000
DEFAULT_HELP_DAILY_INR = 500
SYSTEM_HOUSEHOLD = "_system"  # audit partition for events that belong to no household (unknown senders)

# Everything a household owns; delete_household wipes exactly these partitions.
HOUSEHOLD_COLLECTIONS = ("members", "prefs", "orders", "mandate", "txns", "audit", "purchases", "sessions",
                         "rules", "pending_actions", "counters")

# Role templates for members added by the admin. Category scopes of house_help and teen come from the
# base Cedar policies; personal limits here are soft (above them the admin approves).
ROLE_TEMPLATES: dict[str, dict] = {
    "adult": {"summary": "any category; orders above the approval limit go to the admin"},
    "elder": {"summary": "any category; orders above the approval limit go to the admin"},
    "house_help": {"daily_cap_inr": DEFAULT_HELP_DAILY_INR,
                   "summary": "staples, dairy, vegetables, fruits and cleaning"},
    "teen": {"summary": "stationery and snacks only, no energy drinks"},
}


class DirectoryError(Exception):
    pass


def slug(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower()).split()
    return (words[0] if words else "member")[:20]


def expand_categories(cats: list[str] | None) -> list[str]:
    from .domain import CATEGORIES

    out: list[str] = []
    for c in cats or []:
        c = str(c).strip().lower().replace(" ", "_")
        for x in (GROCERIES if c in ("groceries", "grocery", "ration", "kirana") else (c,)):
            if x in CATEGORIES and x not in out:
                out.append(x)
    return out


class Directory:
    def __init__(self, repo: Repository, clock: Clock | None = None) -> None:
        self.repo = repo.base if isinstance(repo, ScopedRepository) else repo
        self.clock = clock or Clock()

    def scoped(self, household_id: str) -> ScopedRepository:
        return ScopedRepository(self.repo, household_id)

    # ---------- demo household ----------
    def ensure_demo(self, demo_phones: set[str] | None = None) -> None:
        """Seed the Gupta family once; flag the owner's phone(s) as demo."""
        if self.repo.get("households", DEMO_HOUSEHOLD_ID) is None:
            raw = demo_household_raw()
            profile = {k: raw[k] for k in ("household_id", "name", "city", "mandate")}
            profile.update(demo=True, created_at=self.clock.now().isoformat())
            sr = self.scoped(DEMO_HOUSEHOLD_ID)
            for m in raw["members"]:
                # Mom's phone stays the literal ADMIN_PHONE_PLACEHOLDER in storage and is resolved from
                # JHOLA_ADMIN_PHONE on load, so the demo admin follows the deployment's configuration.
                sr.put("members", m["id"], {**Member.from_doc(m).to_doc(), "phone": m["phone"]})
                self.repo.put_new("phones", Member.from_doc(m).phone,
                                  {"household_id": DEMO_HOUSEHOLD_ID, "member_id": m["id"], "demo": False})
            self.seed_demo_preferences()
            self.repo.put("households", DEMO_HOUSEHOLD_ID, profile)
        admin_phone = to_e164(config.ADMIN_PHONE)
        if self.repo.get("phones", admin_phone) is None:  # JHOLA_ADMIN_PHONE changed since the seed
            self.repo.put_new("phones", admin_phone, {"household_id": DEMO_HOUSEHOLD_ID, "member_id": "mom",
                                                      "demo": False})
        for p in demo_phones or ():
            doc = self.repo.get("phones", p)
            if doc is None:
                admin = self.load(DEMO_HOUSEHOLD_ID).admins()[0]
                self.repo.put_new("phones", p, {"household_id": DEMO_HOUSEHOLD_ID, "member_id": admin.id,
                                                "demo": True})
            elif doc["household_id"] == DEMO_HOUSEHOLD_ID and not doc.get("demo"):
                self.repo.put("phones", p, {**doc, "demo": True})

    def seed_demo_preferences(self) -> None:
        sr = self.scoped(DEMO_HOUSEHOLD_ID)
        sr.delete_collection("prefs")
        for word, p in demo_household_raw()["preferences"].items():
            sr.put("prefs", word, {"word": word, "sku": p["sku"], "qty": p.get("qty", 1), "source": "seed"})

    # ---------- lookup ----------
    def lookup(self, phone: str) -> dict | None:
        """{household_id, member_id, demo} for a phone, or None for a number Jhola has never seen."""
        p = to_e164(phone)
        return self.repo.get("phones", p) if p else None

    def profile(self, household_id: str) -> dict | None:
        return self.repo.get("households", household_id)

    def load(self, household_id: str) -> Household:
        profile = self.profile(household_id)
        if profile is None:
            raise DirectoryError(f"no household {household_id}")
        sr = self.scoped(household_id)
        raw = dict(profile)
        raw["members"] = sorted(sr.list("members"), key=lambda m: (m.get("role") != "admin", m.get("added_at", ""),
                                                                  m["id"]))
        raw["preferences"] = {p["word"]: p for p in sr.list("prefs")}
        raw["purchase_history"] = demo_household_raw()["purchase_history"] if profile.get("demo") else []
        return Household(raw, sr)

    def list_households(self) -> list[dict]:
        out = []
        for p in sorted(self.repo.list("households"), key=lambda h: h.get("created_at", "")):
            members = [{**m, "phone": Member.from_doc(m).phone}  # resolves the demo admin's placeholder
                       for m in self.scoped(p["household_id"]).list("members")]
            out.append({**p, "members": members})
        return out

    # ---------- create ----------
    def create_household(self, admin_phone: str, admin_name: str, home_name: str = "",
                         monthly_budget_inr: int = DEFAULT_BUDGET_INR,
                         approval_threshold_inr: int = DEFAULT_THRESHOLD_INR, language: str = "hinglish") -> Household:
        phone = to_e164(admin_phone)
        hid = f"hh-{uuid.uuid4().hex[:10]}"
        admin_name = (admin_name or "").strip()[:40] or "Admin"
        mid = slug(admin_name)
        if not self.repo.put_new("phones", phone, {"household_id": hid, "member_id": mid, "demo": False}):
            raise DirectoryError("this number already belongs to a Jhola household")
        now = self.clock.now().isoformat()
        profile = {
            "household_id": hid, "name": (home_name or f"{admin_name}'s home").strip()[:60], "demo": False,
            "created_at": now,
            "mandate": {"mandate_id": f"MNDT-{hid[3:].upper()}-0001", "payer_vpa": f"{mid}.{hid[3:9]}@simbank",
                        "payee": "Jhola Kirana (SIMULATED)", "monthly_cap_inr": int(monthly_budget_inr),
                        "per_payment_approval_above_inr": int(approval_threshold_inr),
                        "house_help_daily_cap_inr": DEFAULT_HELP_DAILY_INR},
        }
        self.scoped(hid).put("members", mid, {**Member(mid, admin_name, admin_name, "admin", phone, language).to_doc(),
                                             "added_at": now})
        self.repo.put("households", hid, profile)
        return self.load(hid)

    # ---------- members ----------
    def new_member_id(self, hh: Household, name: str) -> str:
        base, ids = slug(name), {m.id for m in hh.members}
        mid, n = base, 1
        while mid in ids:
            n += 1
            mid = f"{base}{n}"
        return mid

    def add_member(self, hh: Household, name: str, phone: str, role: str, daily_cap_inr: int | None = None,
                   order_cap_inr: int | None = None, allowed_categories: list[str] | None = None,
                   language: str = "hinglish", added_by: str = "", member_id: str | None = None) -> Member:
        p = to_e164(phone)
        mid = member_id or self.new_member_id(hh, name)
        if not self.repo.put_new("phones", p, {"household_id": hh.id, "member_id": mid, "demo": False}):
            raise DirectoryError("this number already belongs to a Jhola household")
        self.repo.delete("onboarding", p)  # an invitation replaces a half-finished onboarding
        m = Member(mid, name.strip()[:40], name.strip()[:40], role, p, language, daily_cap_inr, order_cap_inr,
                   list(allowed_categories or []), welcomed=False)
        self.scoped(hh.id).put("members", mid, {**m.to_doc(), "added_by": added_by,
                                                "added_at": self.clock.now().isoformat()})
        hh.members.append(m)
        return m

    def save_member(self, household_id: str, m: Member) -> None:
        sr = self.scoped(household_id)
        old = sr.get("members", m.id) or {}
        doc = {**old, **m.to_doc()}
        if old.get("phone") == "ADMIN_PHONE_PLACEHOLDER":
            doc["phone"] = old["phone"]
        sr.put("members", m.id, doc)

    def remove_member(self, hh: Household, member_id: str) -> None:
        """Remove the member and their personal data (conversation, phone index, 24h-window marker)."""
        m = hh.member(member_id)
        sr = self.scoped(hh.id)
        sr.delete("members", member_id)
        sr.delete("sessions", m.phone)
        idx = self.repo.get("phones", m.phone)
        if idx and idx.get("household_id") == hh.id:
            self.repo.delete("phones", m.phone)
        self.repo.delete("wa_last_inbound", m.phone)
        self.repo.delete("demo_acting", m.phone)
        hh.members = [x for x in hh.members if x.id != member_id]

    def update_mandate_settings(self, hh: Household, monthly_cap_inr: int | None = None,
                                approval_threshold_inr: int | None = None) -> dict:
        profile = self.profile(hh.id)
        md = profile["mandate"]
        if monthly_cap_inr is not None:
            md["monthly_cap_inr"] = int(monthly_cap_inr)
            live = self.scoped(hh.id).get("mandate", md["mandate_id"])
            if live:
                live["monthly_cap_inr"] = int(monthly_cap_inr)
                self.scoped(hh.id).put("mandate", md["mandate_id"], live)
        if approval_threshold_inr is not None:
            md["per_payment_approval_above_inr"] = int(approval_threshold_inr)
        self.repo.put("households", hh.id, profile)
        hh.mandate.update(md)
        return md

    def delete_household(self, household_id: str) -> None:
        if household_id == DEMO_HOUSEHOLD_ID:
            raise DirectoryError("the demo household cannot be deleted")
        sr = self.scoped(household_id)
        for m in sr.list("members"):
            idx = self.repo.get("phones", m.get("phone", ""))
            if idx and idx.get("household_id") == household_id:
                self.repo.delete("phones", m["phone"])
            self.repo.delete("wa_last_inbound", m.get("phone", ""))
        for c in HOUSEHOLD_COLLECTIONS:
            sr.delete_collection(c)
        self.repo.delete("households", household_id)


def demo_phones_from_env() -> set[str]:
    import os

    raw = os.environ.get("JHOLA_DEMO_PHONES")
    if raw is None:
        raw = config.ADMIN_PHONE if not config.ADMIN_PHONE.startswith("+9199999") else ""
    return {to_e164(p) for p in raw.split(",") if p.strip()}
