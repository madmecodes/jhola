"""Household administration in plain words: members, limits, rules, budget, delegation.

Nothing here changes the household directly from a chat message. Every change is first stored as a
pending action (collection pending_actions) and shown to the admin with Yes / No buttons; only
confirm() applies it. Both propose and confirm check the role IN CODE and audit refused attempts,
so a non-admin (or a model that was talked into it) cannot manage members or rules.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from . import rules as rules_mod
from .domain import ALLERGENS, CATEGORIES, DIET_PROFILES, ROLES, Household, Member, normalize_allergen
from .household import ROLE_TEMPLATES, DirectoryError, expand_categories
from .orders import Jhola
from .phones import mask_phone, to_e164, valid_mobile

MAX_MEMBERS = 12
MAX_DELEGATION_DAYS = 92
PENDING_TTL_HOURS = 24


class NotAllowed(Exception):
    pass


def limits_text(m: Member, hh: Household) -> str:
    """One line describing what a member may do (role template + personal limits + delegation)."""
    thr = hh.mandate["per_payment_approval_above_inr"]
    if m.role == "admin":
        return "admin: any category, approves orders, manages family, rules and budget"
    if m.allowed_categories:
        scope = ", ".join(m.allowed_categories) + " only"
    else:
        scope = ROLE_TEMPLATES.get(m.role, {}).get("summary", "any category")
    parts = [scope]
    if m.daily_cap_inr is not None:
        parts.append(f"up to Rs {m.daily_cap_inr} a day on their own")
    elif m.role == "house_help":
        parts.append(f"up to Rs {hh.mandate['house_help_daily_cap_inr']} a day")
    if m.order_cap_inr is not None:
        parts.append(f"up to Rs {m.order_cap_inr} per order on their own")
    parts.append(f"orders above Rs {thr} need {hh.admin_label()}'s approval")
    if m.delegation:
        u = str(m.delegation["until"])
        parts.append(f"temporary: may spend Rs {m.delegation['cap_inr']} until {u[:4]}-{u[4:6]}-{u[6:]}")
    if m.diet_text():
        parts.append("diet: " + m.diet_text())
    return "; ".join(parts)


class HouseholdAdmin:
    def __init__(self, app: Jhola, llm: rules_mod.Llm | None = None) -> None:
        self.app = app
        self.hh = app.hh
        self.llm = llm

    # ---------- guard ----------
    def require_admin(self, actor: Member, what: str, **detail) -> None:
        if actor.role != "admin" or self.hh.find(actor.id) is None:
            self.app.audit.log("admin_action_denied", actor=actor.id, attempted=what, role=actor.role, **detail)
            raise NotAllowed(f"Only the household admin ({self.hh.admin_label()}) can {what}.")

    # ---------- read only ----------
    def members(self) -> list[dict]:
        return [{"id": m.id, "name": m.display, "role": m.role, "phone": mask_phone(m.phone),
                 "can": limits_text(m, self.hh), "has_messaged_jhola": m.welcomed} for m in self.hh.members]

    def rules(self) -> list[dict]:
        """Custom rules and delegations, numbered the way "remove rule N" refers to them."""
        today = self.app.clock.today().isoformat()
        out = []
        for i, r in enumerate(rules_mod.custom_rules(self.app.repo), 1):
            row = {"number": i, "id": r["id"], "title": r.get("title", ""), "kind": r.get("kind", "rule")}
            if r.get("expires_on"):
                row.update(expires_on=r["expires_on"], expired=r["expires_on"] < today)
            out.append(row)
        return out

    # ---------- proposals ----------
    def _propose(self, actor: Member, kind: str, params: dict, summary: str) -> dict:
        aid = uuid.uuid4().hex[:10]
        doc = {"id": aid, "kind": kind, "params": params, "summary": summary, "status": "pending",
               "created_by": actor.id, "created_at": self.app.clock.now().isoformat()}
        self.app.repo.put("pending_actions", aid, doc)
        self.app.audit.log("admin_action_proposed", actor=actor.id, action_id=aid, kind=kind, params=params)
        return {"needs_confirmation": True, "action_id": aid, "summary": summary,
                "note": "NOT done yet. The admin gets Yes / No buttons; nothing changes until they tap Yes."}

    def propose_add_member(self, actor: Member, name: str, phone: str, role: str = "adult",
                           daily_limit_inr: int | None = None, per_order_limit_inr: int | None = None,
                           categories: list[str] | None = None, custom_conditions: str = "",
                           language: str = "hinglish") -> dict:
        self.require_admin(actor, "add family members", name=name)
        name = (name or "").strip()
        role = (role or "adult").strip().lower().replace(" ", "_")
        p = to_e164(phone)
        if not name:
            return {"error": "the member's name is missing"}
        if role not in ROLES or role == "admin":
            return {"error": f"role must be one of adult, house_help, teen, elder (got {role!r})"}
        if not valid_mobile(p):
            return {"error": f"{phone!r} does not look like a mobile number; ask for the 10 digit number"}
        if len(self.hh.members) >= MAX_MEMBERS:
            return {"error": f"a household can have at most {MAX_MEMBERS} members"}
        if self.hh.member_by_phone(p):
            return {"error": f"{mask_phone(p)} is already {self.hh.member_by_phone(p).display} in this household"}
        if self.app.directory.lookup(p):
            return {"error": "this number already belongs to another Jhola household"}
        cats = expand_categories(categories)
        if categories and not cats:
            return {"error": f"unknown categories; use: groceries, {', '.join(CATEGORIES)}"}
        tpl = ROLE_TEMPLATES.get(role, {})
        daily = _cap(daily_limit_inr) if daily_limit_inr is not None else tpl.get("daily_cap_inr")
        member_id = self.app.directory.new_member_id(self.hh, name)
        m = Member(member_id, name[:40], name[:40], role, p, language or "hinglish", daily,
                   _cap(per_order_limit_inr), cats, welcomed=False)
        params = {"member": m.to_doc()}
        summary = (f"Add *{m.display}* ({mask_phone(p)}) as {role.replace('_', ' ')}.\n"
                   f"Can order: {limits_text(m, self.hh)}.")
        if custom_conditions.strip():
            rule = self._draft(f'Only for {m.display} (Member::"{m.id}", role {m.role}): {custom_conditions.strip()}',
                               extra_member=m)
            if rule.get("ok"):
                params["rule"] = rule["rule"]
                summary += f"\nExtra rule: {rule['rule']['title']} ({rule['rule']['explanation']})"
            else:
                summary += (f"\nI could not turn \"{custom_conditions.strip()[:80]}\" into a safe rule "
                            f"({rule['error']}). {m.display} will be added without it.")
        return self._propose(actor, "add_member", params, summary + "\nAdd karein?")

    def propose_remove_member(self, actor: Member, member: str) -> dict:
        self.require_admin(actor, "remove family members", member=member)
        m = self.hh.find_by_name(member)
        if m is None:
            return {"error": f"no member called {member!r}", "members": [x.display for x in self.hh.members]}
        if m.id == actor.id:
            return {"error": "to remove yourself send: delete my data"}
        return self._propose(actor, "remove_member", {"member_id": m.id},
                             f"Remove *{m.display}* ({mask_phone(m.phone)}) from {self.hh.name}? "
                             f"Their chat history is deleted; past orders stay in the household record.")

    def propose_change_limit(self, actor: Member, member: str, daily_limit_inr: int | None = None,
                             per_order_limit_inr: int | None = None, categories: list[str] | None = None) -> dict:
        self.require_admin(actor, "change limits", member=member)
        m = self.hh.find_by_name(member)
        if m is None:
            return {"error": f"no member called {member!r}", "members": [x.display for x in self.hh.members]}
        if m.role == "admin":
            return {"error": "the admin has no personal limits"}
        params: dict = {"member_id": m.id}
        changes = []
        if daily_limit_inr is not None:
            params["daily_cap_inr"] = _cap(daily_limit_inr)
            changes.append(f"daily limit Rs {m.daily_cap_inr} -> " + _show(params["daily_cap_inr"]))
        if per_order_limit_inr is not None:
            params["order_cap_inr"] = _cap(per_order_limit_inr)
            changes.append(f"per-order limit Rs {m.order_cap_inr} -> " + _show(params["order_cap_inr"]))
        if categories is not None:
            cats = expand_categories(categories)
            if categories and not cats:
                return {"error": f"unknown categories; use: groceries, {', '.join(CATEGORIES)}"}
            params["allowed_categories"] = cats
            changes.append("categories -> " + (", ".join(cats) if cats else "role default"))
        if not changes:
            return {"error": "say what to change: daily limit, per-order limit or categories"}
        return self._propose(actor, "change_limit", params,
                             f"Change for *{m.display}*: " + "; ".join(changes).replace("Rs None", "none") + ". Theek hai?")

    def propose_budget_change(self, actor: Member, monthly_budget_inr: int | None = None,
                              approval_threshold_inr: int | None = None) -> dict:
        self.require_admin(actor, "change the budget")
        md = self.hh.mandate
        params, changes = {}, []
        if monthly_budget_inr is not None:
            b = int(monthly_budget_inr)
            if not 100 <= b <= 200000:
                return {"error": "the monthly budget must be between Rs 100 and Rs 2,00,000"}
            spent = self.app.month_spent()
            if b < spent:
                return {"error": f"Rs {spent} is already spent this month; the budget cannot go below that"}
            params["monthly_cap_inr"] = b
            changes.append(f"monthly budget Rs {md['monthly_cap_inr']} -> Rs {b}")
        if approval_threshold_inr is not None:
            t = int(approval_threshold_inr)
            if not 0 <= t <= 200000:
                return {"error": "the approval limit must be between Rs 0 and Rs 2,00,000"}
            params["approval_threshold_inr"] = t
            changes.append(f"approval needed above Rs {md['per_payment_approval_above_inr']} -> Rs {t}")
        if not changes:
            return {"error": "say the new monthly budget or the new approval limit"}
        return self._propose(actor, "budget", params,
                             "Change " + "; ".join(changes) + " (simulated UPI AutoPay mandate). Theek hai?")

    def propose_rule(self, actor: Member, text: str) -> dict:
        self.require_admin(actor, "add rules", text=text[:200])
        rule = self._draft(text.strip())
        if not rule.get("ok"):
            return {"error": f"could not write a safe rule for that: {rule['error']}"}
        r = rule["rule"]
        tests = "; ".join(f"{t['case']}: {t['actual']}" for t in r.get("tests", [])[:3])
        return self._propose(actor, "add_rule", {"rule": r},
                             f"New rule: *{r['title']}*\n{r['explanation']}\n"
                             + (f"Checked: {tests}\n" if tests else "") + "Rule lagayein?")

    def propose_remove_rule(self, actor: Member, number: int) -> dict:
        self.require_admin(actor, "remove rules", number=number)
        rows = self.rules()
        row = next((r for r in rows if r["number"] == int(number)), None)
        if row is None:
            return {"error": f"there is no rule {number}", "rules": rows}
        return self._propose(actor, "remove_rule", {"rule_id": row["id"], "title": row["title"]},
                             f"Remove rule {row['number']}: *{row['title']}*?")

    def propose_delegation(self, actor: Member, member: str, amount_inr: int, until_date: str) -> dict:
        self.require_admin(actor, "delegate spending", member=member)
        m = self.hh.find_by_name(member)
        if m is None:
            return {"error": f"no member called {member!r}", "members": [x.display for x in self.hh.members]}
        if m.role == "admin":
            return {"error": "the admin does not need a delegation"}
        today = self.app.clock.today()
        try:
            until = date.fromisoformat(str(until_date)[:10])
        except ValueError:
            return {"error": "until_date must be a date like 2026-09-27"}
        if until < today or until > today + timedelta(days=MAX_DELEGATION_DAYS):
            return {"error": f"the end date must be between today and {MAX_DELEGATION_DAYS} days from now"}
        amount = int(amount_inr)
        if amount <= 0:
            return {"error": "the amount must be positive"}
        title = f"{m.display} can spend up to Rs {amount} without approval until {until.isoformat()}"
        return self._propose(actor, "delegate",
                             {"member_id": m.id, "cap_inr": amount, "starts_on": today.isoformat(),
                              "expires_on": until.isoformat(), "title": title},
                             f"Temporary permission: *{title}*. It ends on its own after that date; the monthly "
                             f"budget and category rules still apply. Theek hai?")

    def propose_diet_change(self, actor: Member, member: str, diet_profile: str | None = None,
                            add_allergies: list[str] | None = None, remove_allergies: list[str] | None = None,
                            vrat_until: str | None = None, max_caffeine_mg: int | None = None) -> dict:
        self.require_admin(actor, "set dietary rules", member=member)
        m = self.hh.find_by_name(member)
        if m is None:
            return {"error": f"no member called {member!r}", "members": [x.display for x in self.hh.members]}
        params: dict = {"member_id": m.id}
        changes = []
        if diet_profile is not None:
            dp = str(diet_profile).strip().lower().replace("vegetarian", "veg").replace("jain_friendly", "jain")
            dp = {"pure veg": "veg", "shakahari": "veg", "non-veg": "none", "nonveg": "none", "no": "none",
                  "": "none"}.get(dp, dp)
            if dp not in DIET_PROFILES:
                return {"error": f"diet_profile must be one of {', '.join(DIET_PROFILES)}"}
            params["diet_profile"] = dp
            changes.append(f"diet {m.diet_profile} -> {dp}")
        allergies = list(m.allergies)
        unknown = []
        for w in add_allergies or []:
            a = normalize_allergen(str(w))
            if a is None:
                unknown.append(str(w))
            elif a not in allergies:
                allergies.append(a)
        for w in remove_allergies or []:
            a = normalize_allergen(str(w))
            if a in allergies:
                allergies.remove(a)
        if unknown:
            return {"error": f"I do not know the allergen(s) {', '.join(unknown)}; I can track: "
                             f"{', '.join(ALLERGENS)}"}
        if add_allergies or remove_allergies:
            params["allergies"] = allergies
            changes.append("allergies -> " + (", ".join(a.replace("_", " ") for a in allergies) or "none"))
        if vrat_until is not None:
            v = str(vrat_until).strip().lower()
            if v in ("", "none", "no", "end", "over"):
                params["vrat_until"] = None
                changes.append("vrat ended")
            else:
                try:
                    until = date.fromisoformat(v[:10])
                except ValueError:
                    return {"error": "vrat_until must be a date like 2026-10-02"}
                today = self.app.clock.today()
                if until < today or until > today + timedelta(days=MAX_DELEGATION_DAYS):
                    return {"error": f"the vrat end date must be between today and {MAX_DELEGATION_DAYS} days from now"}
                params["vrat_until"] = until.isoformat()
                changes.append(f"vrat (only vrat-friendly food) until {until.isoformat()}")
        if max_caffeine_mg is not None:
            c = int(max_caffeine_mg)
            params["max_caffeine_mg"] = None if c < 0 else c
            changes.append("caffeine limit removed" if c < 0 else
                           ("no caffeinated drinks" if c == 0 else f"max {c} mg caffeine per order"))
        if not changes:
            return {"error": "say what to set: diet (veg / vegan / jain / eggetarian), an allergy, a vrat end "
                             "date or a caffeine limit"}
        return self._propose(actor, "diet", params,
                             f"Diet for *{m.display}*: " + "; ".join(changes) + ". Orders for {0} that break this "
                             "will be blocked, whoever orders. Theek hai?".format(m.display))

    def _draft(self, text: str, extra_member: Member | None = None) -> dict:
        hh = self.hh
        if extra_member is not None:  # draft and test the rule against the household WITH the new member
            raw = {**hh.raw, "members": [m.to_doc() for m in hh.members] + [extra_member.to_doc()],
                   "preferences": {}}
            hh = Household(raw, hh.repo)
        try:
            d = rules_mod.draft_rule(text, self.llm, household=hh, today=self.app.today_int())
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"rule drafting failed ({type(e).__name__})"}
        if not d["validation"]["ok"]:
            return {"ok": False, "error": "the Cedar validator rejected the draft"}
        tests = d.get("test_results") or []
        if any(not t["pass"] for t in tests):
            failed = next(t for t in tests if not t["pass"])
            return {"ok": False, "error": f"its own test failed: {failed['case']}"}
        return {"ok": True, "rule": {"title": d["title"], "cedar": d["cedar"],
                                     "explanation": d.get("explanation_hinglish") or d.get("explanation_en", ""),
                                     "explanation_en": d.get("explanation_en", ""),
                                     "tests": [{"case": t["case"], "actual": t["actual"]} for t in tests]}}

    # ---------- confirm / cancel ----------
    def _pending(self, actor: Member, action_id: str) -> dict:
        self.require_admin(actor, "confirm household changes", action_id=action_id)
        doc = self.app.repo.get("pending_actions", action_id)
        if not doc or doc.get("status") != "pending":
            raise NotAllowed("Yeh request ab pending nahi hai.")
        age = self.app.clock.now() - _parse(doc["created_at"])
        if age > timedelta(hours=PENDING_TTL_HOURS):
            doc["status"] = "expired"
            self.app.repo.put("pending_actions", action_id, doc)
            raise NotAllowed("Yeh request purani ho gayi. Dobara boliye.")
        return doc

    def cancel(self, actor: Member, action_id: str) -> str:
        doc = self._pending(actor, action_id)
        doc["status"] = "cancelled"
        self.app.repo.put("pending_actions", action_id, doc)
        self.app.audit.log("admin_action_cancelled", actor=actor.id, action_id=action_id, kind=doc["kind"])
        return "Theek hai, kuch nahi badla."

    def confirm(self, actor: Member, action_id: str) -> str:
        doc = self._pending(actor, action_id)
        try:
            text = self._apply(actor, doc)
        except DirectoryError as e:
            doc.update(status="failed", error=str(e))
            self.app.repo.put("pending_actions", action_id, doc)
            return f"Nahi ho paya: {e}."
        doc.update(status="done", done_at=self.app.clock.now().isoformat())
        self.app.repo.put("pending_actions", action_id, doc)
        self.app.audit.log("admin_action_confirmed", actor=actor.id, action_id=action_id, kind=doc["kind"],
                           params=doc["params"])
        return text

    def _apply(self, actor: Member, doc: dict) -> str:
        app, p, now = self.app, doc["params"], self.app.clock.now().isoformat()
        kind = doc["kind"]
        if kind == "add_member":
            d = p["member"]
            m = app.directory.add_member(self.hh, d["name"], d["phone"], d["role"], d.get("daily_cap_inr"),
                                         d.get("order_cap_inr"), d.get("allowed_categories"),
                                         d.get("language", "hinglish"), added_by=actor.id, member_id=d["id"])
            app.audit.log("member_added", actor=actor.id, member=m.id, role=m.role, limits=limits_text(m, self.hh))
            text = (f"Done. *{m.display}* is now part of {self.hh.name}.\n"
                    f"Ask them to send \"hi\" to this number from {mask_phone(m.phone)}. Jhola will recognise them "
                    f"and explain what they can order. (WhatsApp does not let me message them first.)")
            if p.get("rule"):
                text += "\n" + self._activate(actor, p["rule"])
            return text
        if kind == "remove_member":
            m = self.hh.find(p["member_id"])
            if m is None:
                return "Woh member pehle hi hat chuka hai."
            name = m.display
            app.directory.remove_member(self.hh, m.id)
            app.audit.log("member_removed", actor=actor.id, member=p["member_id"])
            return f"Done. {name} is removed and can no longer order."
        if kind == "change_limit":
            m = self.hh.find(p["member_id"])
            if m is None:
                return "Woh member ab household mein nahi hai."
            if "daily_cap_inr" in p:
                m.daily_cap_inr = p["daily_cap_inr"]
            if "order_cap_inr" in p:
                m.order_cap_inr = p["order_cap_inr"]
            if "allowed_categories" in p:
                m.allowed_categories = p["allowed_categories"]
            app.directory.save_member(self.hh.id, m)
            app.audit.log("member_limits_changed", actor=actor.id, member=m.id, limits=limits_text(m, self.hh))
            return f"Done. {m.display}: {limits_text(m, self.hh)}."
        if kind == "diet":
            m = self.hh.find(p["member_id"])
            if m is None:
                return "Woh member ab household mein nahi hai."
            if "diet_profile" in p:
                m.diet_profile = p["diet_profile"]
            if "allergies" in p:
                m.allergies = list(p["allergies"])
            if "vrat_until" in p:
                m.vrat_until = p["vrat_until"]
            if "max_caffeine_mg" in p:
                m.max_caffeine_mg = p["max_caffeine_mg"]
            app.directory.save_member(self.hh.id, m)
            app.audit.log("member_diet_changed", actor=actor.id, member=m.id, diet=m.diet_text())
            return f"Done. {m.display}: {m.diet_text() or 'no dietary rules'}."
        if kind == "budget":
            md = app.directory.update_mandate_settings(self.hh, p.get("monthly_cap_inr"),
                                                       p.get("approval_threshold_inr"))
            app.audit.log("budget_changed", actor=actor.id, **p)
            return (f"Done. Monthly budget Rs {md['monthly_cap_inr']}, approval needed above "
                    f"Rs {md['per_payment_approval_above_inr']} (simulated mandate).")
        if kind == "add_rule":
            return self._activate(actor, p["rule"])
        if kind == "remove_rule":
            r = rules_mod.deactivate(app.repo, p["rule_id"], now)
            app.audit.log("rule_deactivated", actor=actor.id, rule_id=p["rule_id"], title=p.get("title"))
            return f"Done. Rule removed: {r['title'] if r else p.get('title')}."
        if kind == "delegate":
            r = rules_mod.add_delegation(app.repo, p["member_id"], p["cap_inr"], p["starts_on"], p["expires_on"],
                                         p["title"], now)
            app.audit.log("delegation_added", actor=actor.id, rule_id=r["id"], member=p["member_id"],
                          cap_inr=p["cap_inr"], expires_on=p["expires_on"])
            return f"Done. {p['title']}."
        return "OK"

    def _activate(self, actor: Member, rule: dict) -> str:
        res = rules_mod.activate(self.app.repo, rule["cedar"], rule["title"], self.app.clock.now().isoformat(),
                                 rule.get("explanation", ""), rule.get("explanation_en", ""))
        if not res["ok"]:
            return "Rule could not be activated: " + "; ".join(res["validation"]["errors"])[:200]
        r = res["rule"]
        self.app.audit.log("rule_activated", actor=actor.id, rule_id=r["id"], title=r["title"], cedar=r["cedar"])
        return f"Rule active: {r['title']}."


# ---------- privacy: "delete my data" / "leave" ----------
def _last_admin(app: Jhola, me: Member) -> bool:
    return me.role == "admin" and len(app.hh.admins()) == 1


def leave_prompt(app: Jhola, me: Member) -> tuple[str, list[dict]]:
    buttons = [{"id": "leave:yes", "title": "Yes, delete"}, {"id": "leave:no", "title": "No"}]
    if app.hh.demo and _last_admin(app, me):
        return "Yeh demo household ka admin number hai; ise delete nahi kiya ja sakta.", []
    if _last_admin(app, me):
        others = len(app.hh.members) - 1
        extra = f" and removes the {others} other member(s)" if others else ""
        return (f"You are the only admin of *{app.hh.name}*. This deletes the whole household{extra}: members, "
                f"orders, rules, learned brands and chat history. It cannot be undone. Delete everything?", buttons)
    return (f"This removes you from *{app.hh.name}* and deletes your chat history and phone number from Jhola. "
            f"Past orders stay in the household's record under your first name. Go ahead?", buttons)


def leave_confirm(app: Jhola, me: Member) -> str:
    from .audit import AuditLog
    from .household import SYSTEM_HOUSEHOLD

    if app.hh.demo and _last_admin(app, me):
        return "Yeh demo household ka admin number hai; ise delete nahi kiya ja sakta."
    if _last_admin(app, me):
        hid = app.hh.id
        app.directory.delete_household(hid)
        app.base.delete("wa_last_inbound", me.phone)
        AuditLog(app.directory.scoped(SYSTEM_HOUSEHOLD), app.clock).log("household_deleted", actor="member",
                                                                         household_id=hid)
        return "Done. Your household and all its data are deleted. Send \"hi\" anytime to start again."
    app.directory.remove_member(app.hh, me.id)
    app.audit.log("member_left", actor=me.id)
    return "Done. You are removed and your data is deleted. Send \"hi\" anytime to start again."


def _cap(v) -> int | None:
    """0 or a negative number means "no limit"."""
    if v is None:
        return None
    v = int(v)
    return v if v > 0 else None


def _show(v: int | None) -> str:
    return f"Rs {v}" if v is not None else "none"


def _parse(ts: str):
    from datetime import datetime

    return datetime.fromisoformat(ts)
