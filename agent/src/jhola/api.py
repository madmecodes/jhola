"""Console HTTP API (framework-free). The Lambda adapter lives in api_handler.py.

Every route returns (status, body). Slow work (web chat with Bedrock, rule drafting, the refill job)
goes through a Deferrer: on Lambda it runs in an async worker invocation and the HTTP call waits for
it up to ~25 s (API Gateway's limit is 30 s); if it is still running, the response is
{pending: true, job_id} and GET /api/jobs/{job_id} returns the result later.
"""

from __future__ import annotations

import base64
import json
import re
import time
import uuid
from typing import Any, Callable, Protocol

from . import rules as rules_mod
from .agent import JholaAgent
from .config import Clock
from .domain import Member
from .orders import Jhola
from .redteam import ATTACKS, run_attack
from .store import Repository

MAX_TEXT = 1000
MAX_IMAGE_BYTES = 4 * 1024 * 1024
WEB_MEMBERS = ("didi", "teen", "dad", "mom")
WINDOW_S = 24 * 3600 - 300  # WhatsApp customer-service window, with a 5 minute margin
PHONE_RE = re.compile(r"\+?\d{10,13}")


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def mask_phone(p: str | None) -> str:
    digits = re.sub(r"\D", "", p or "")
    if len(digits) < 6:
        return ""
    return f"+{digits[:2]}******{digits[-4:]}"


def mask_phones(obj: Any) -> Any:
    """Mask phone numbers anywhere in a JSON-able value (audit events carry sender phones)."""
    return json.loads(PHONE_RE.sub(lambda m: mask_phone(m.group(0)), json.dumps(obj, ensure_ascii=False)))


LIMITS = {
    "admin": "Any category. Approves orders above Rs {thr}. Can top up the mandate.",
    "adult": "Any category. Auto-pay up to Rs {thr} per order, above that Mom approves. Max 5 units per item.",
    "house_help": "Staples, dairy, vegetables, fruits and cleaning only. Max Rs {daily} per day. "
                  "Max 5 units per item.",
    "teen": "Stationery and snacks only. No energy drinks. Max 5 units per item.",
}


def order_status(o: dict) -> str:
    st = o.get("status", "")
    if st == "paid" and any(l.get("allowed") is False for l in o.get("lines", [])):
        return "partially_paid"
    return st


def summarize(e: dict) -> str:
    d, ev = e.get("data") or {}, e.get("event", "")
    if ev == "policy_evaluated":
        verdict = "ALLOW" if d.get("allowed") else "DENY"
        what = d.get("sku") or f"order Rs {d.get('cedar_request', {}).get('context', {}).get('order_total_inr')}"
        return f"Cedar {verdict} {d.get('action')} {what} ({', '.join(d.get('policy_ids', []))})"
    if ev == "payment_captured":
        t = d.get("txn", {})
        return f"Paid Rs {t.get('amount_inr')} via UPI mandate, ref {t.get('upi_ref')} (SIMULATED)"
    if ev == "cart_built":
        return f"Cart built: {len(d.get('lines', []))} items, Rs {d.get('total_inr')}"
    if ev == "message_received":
        src = "photo" if d.get("has_image") else (d.get("input_type") or "text")
        return f"Message from {e.get('actor')} ({d.get('channel', 'whatsapp')}, {src}): {(d.get('text') or '')[:80]}"
    if ev == "reply_sent":
        return f"Replied to {d.get('to')}: {(d.get('text') or '')[:80]}"
    if ev == "item_resolved":
        return f"Resolved '{d.get('query')}' -> {d.get('label') or d.get('reason')}"
    if ev == "approval_requested":
        return f"Approval requested for Rs {d.get('amount_inr')}"
    if ev == "approval_response":
        return f"Admin decision: {d.get('decision')}"
    if ev == "order_denied":
        return f"Order denied at {d.get('stage')} stage"
    if ev == "suspicious_content_detected":
        return f"Untrusted seller text on {d.get('sku')} contains instructions; treated as data"
    if ev == "notification_sent":
        return f"Notified {d.get('to')}: {(d.get('text') or '')[:80]}"
    if ev == "items_extracted":
        return f"Parchi read by {d.get('reader')}: {len(d.get('items') or [])} items"
    if ev == "voice_transcribed":
        return f"Voice note ({d.get('language')}): {(d.get('transcript') or '')[:80]}"
    if ev == "rule_activated":
        return f"Custom rule activated: {d.get('title')}"
    if ev == "rule_deactivated":
        return f"Custom rule deactivated: {d.get('title')}"
    if ev == "redteam_run":
        return f"Red-team {d.get('attack')}: {d.get('verdict')}"
    return ev.replace("_", " ")


class Deferrer(Protocol):
    def run(self, kind: str, payload: dict) -> dict: ...


class InlineDeferrer:
    """Runs jobs in-process (local and tests)."""

    def __init__(self) -> None:
        self.api: ConsoleApi | None = None

    def run(self, kind: str, payload: dict) -> dict:
        return self.api.execute_job(kind, payload)


class ConsoleApi:
    def __init__(self, repo: Repository, clock: Clock | None = None, model_factory: Callable | None = None,
                 vision=None, llm: rules_mod.Llm | None = None, deferrer: Deferrer | None = None,
                 sender: Callable[[str, str, list[dict]], list[str]] | None = None,
                 admin_phone: str | None = None) -> None:
        self.repo = repo
        self.clock = clock or Clock()
        self.model_factory = model_factory
        self.vision = vision
        self.llm = llm
        self.deferrer = deferrer or InlineDeferrer()
        if isinstance(self.deferrer, InlineDeferrer):
            self.deferrer.api = self
        self.sender = sender  # (to_phone, text, buttons) -> message ids; sends WhatsApp
        self._admin_phone = admin_phone

    # ---------- plumbing ----------
    def app(self) -> Jhola:
        return Jhola(self.repo, self.clock)

    def agent(self, app: Jhola | None = None) -> JholaAgent:
        return JholaAgent(app or self.app(), self.model_factory, self.vision)

    def now(self) -> str:
        return self.clock.now().isoformat()

    # ---------- formatting ----------
    def format_order(self, app: Jhola, o: dict) -> dict:
        m = next((x for x in app.hh.members if x.id == o.get("member_id")), None)
        items = []
        for l in o.get("lines", []):
            p = app.catalog.get(l["sku"]) or {}
            allowed = l.get("allowed")
            items.append({
                "sku": l["sku"], "name": p.get("name", l.get("label")), "brand": p.get("brand", ""),
                "qty": l["qty"], "price_inr": l["unit_price_inr"], "line_total_inr": l["line_total_inr"],
                "decision": "pending" if allowed is None else ("allow" if allowed else "deny"),
                "policy_ids": l.get("policy_ids", []), "reason": "; ".join(r for r in l.get("reasons", []) if r),
                "reason_hinglish": "; ".join(r for r in l.get("reasons_hinglish", []) if r),
                "amazon_search_url": p.get("amazon_search_url", ""), "fulfilment": p.get("fulfilment", ""),
                "category": p.get("category", l.get("category")),
            })
        txn = o.get("txn") or {}
        extra = {}
        if o.get("status") == "pending_approval":
            extra["approval_reasons"] = (o.get("approval_reasons") or {}).get("reasons", [])
        if o.get("deny_reasons"):
            extra["deny_reasons"] = o["deny_reasons"].get("reasons", [])
        return {
            "order_id": o["order_id"], "member_id": o.get("member_id"),
            "member_name": m.display if m else o.get("member_id"), "role": m.role if m else "",
            "created_at": o.get("created_at"), "status": order_status(o), "total_inr": o.get("total_inr", 0),
            "payable_inr": o.get("payable_inr", o.get("total_inr", 0)), "paid_inr": o.get("paid_amount_inr", 0),
            "upi_ref": txn.get("upi_ref"), "simulated_payment": True, "items": items,
            "channel": o.get("channel", "whatsapp"), "input_type": o.get("input_type", "text"), **extra,
        }

    @staticmethod
    def format_event(e: dict) -> dict:
        return mask_phones({"seq": e.get("seq"), "ts": e.get("ts"), "order_id": e.get("order_id"),
                            "type": e.get("event"), "actor": e.get("actor"), "summary": summarize(e),
                            "data": e.get("data") or {}})

    def decisions_for(self, app: Jhola, order_id: str) -> list[dict]:
        return [
            {"action": e["data"]["action"], "sku": e["data"].get("sku"), "allowed": e["data"]["allowed"],
             "policy_ids": e["data"]["policy_ids"], "reasons": e["data"]["reasons"]}
            for e in app.audit.events(order_id) if e["event"] == "policy_evaluated"
        ]

    # ---------- GET ----------
    def household(self) -> dict:
        app = self.app()
        md = app.hh.mandate
        members = [{"id": m.id, "name": m.name, "display": m.display, "role": m.role,
                    "phone_masked": mask_phone(m.phone),
                    "limits_summary": LIMITS.get(m.role, "").format(thr=md["per_payment_approval_above_inr"],
                                                                    daily=md["house_help_daily_cap_inr"])}
                   for m in app.hh.members]
        rules = [{**r, "active": True} for r in rules_mod.base_rules()]
        rules += [{"id": r["id"], "title_en": r["title"], "title_hinglish": r.get("title_hinglish", ""),
                   "cedar": r["cedar"], "source": "custom", "active": True, "created_at": r.get("created_at")}
                  for r in rules_mod.custom_rules(self.repo)]
        m = app.upi.get(app.mandate_id)
        return {
            "household": {"name": app.hh.name, "city": app.hh.raw.get("city")},
            "members": members,
            "rules": rules,
            "mandate": {"cap_inr": m["monthly_cap_inr"], "used_inr": m["month_spent_inr"],
                        "remaining_inr": m["monthly_cap_inr"] - m["month_spent_inr"], "period": "monthly",
                        "month": m["month"], "mandate_id": m["mandate_id"], "simulated": True,
                        "approval_threshold_inr": md["per_payment_approval_above_inr"],
                        "house_help_daily_cap_inr": md["house_help_daily_cap_inr"]},
        }

    def orders(self, limit: int = 20) -> dict:
        app = self.app()
        orders = sorted(self.repo.list("orders"), key=lambda o: (o.get("created_at", ""), o["order_id"]),
                        reverse=True)
        orders = [o for o in orders if o.get("status") != "draft"][: max(1, min(limit, 100))]
        return {"orders": [self.format_order(app, o) for o in orders]}

    def audit(self, order_id: str | None = None, limit: int = 100) -> dict:
        limit = max(1, min(limit, 500))
        if order_id:
            evs = [e for e in self.repo.recent("audit", 3000) if e.get("order_id") == order_id][-limit:]
        else:
            evs = self.repo.recent("audit", limit)
        evs.sort(key=lambda e: e.get("seq", 0))
        return {"events": [self.format_event(e) for e in evs]}

    def approvals(self) -> dict:
        app = self.app()
        pending = sorted((o for o in self.repo.list("orders") if o.get("status") == "pending_approval"),
                         key=lambda o: o.get("created_at", ""), reverse=True)
        return {"pending": [
            {"order_id": o["order_id"], "member_name": app.hh.member(o["member_id"]).display,
             "total_inr": o.get("payable_inr", o.get("total_inr")), "items_count": sum(
                 1 for l in o["lines"] if l.get("allowed")), "created_at": o.get("created_at"),
             "reasons": (o.get("approval_reasons") or {}).get("reasons", [])}
            for o in pending]}

    def job(self, job_id: str) -> dict:
        j = self.repo.get("web_jobs", job_id)
        if not j:
            raise ApiError(404, "no such job")
        return {"job_id": job_id, "kind": j.get("kind"), "status": j.get("status"), "result": j.get("result"),
                "error": j.get("error")}

    # ---------- approvals ----------
    def decide(self, order_id: str, body: dict) -> dict:
        decision = str(body.get("decision", "")).lower()
        if decision not in ("approve", "reject"):
            raise ApiError(400, "decision must be approve or reject")
        app = self.app()
        o = app.get_order(order_id)
        if not o:
            raise ApiError(404, f"no such order {order_id}")
        if o["status"] != "pending_approval":
            raise ApiError(409, f"order {order_id} is {o['status']}, not awaiting approval")
        admin = app.hh.admins()[0]
        res = app.handle_approval(admin, order_id, decision)
        app.audit.log("console_approval", order_id, actor=admin.id, decision=decision, channel="web",
                      result=res.get("status"))
        app.drain_outbox()  # the requester's notification is shown in the console, not sent to WhatsApp
        return self.format_order(app, app.get_order(order_id))

    # ---------- chat ----------
    def chat(self, body: dict, client_id: str = "") -> dict:
        member = str(body.get("member", "")).lower()
        if member not in WEB_MEMBERS:
            raise ApiError(400, f"member must be one of {', '.join(WEB_MEMBERS)}")
        text = body.get("text")
        if text is not None and not isinstance(text, str):
            raise ApiError(400, "text must be a string")
        text = (text or "").strip()
        if len(text) > MAX_TEXT:
            raise ApiError(400, f"text longer than {MAX_TEXT} characters")
        button_id = str(body.get("button_id") or "")
        if button_id and not button_id.startswith("order:"):
            raise ApiError(400, "only order:<id> buttons are supported here; use /api/approvals for approvals")
        image_b64 = body.get("image_base64")
        if image_b64:
            try:
                raw = base64.b64decode(image_b64.split(",", 1)[-1], validate=False)
            except Exception:  # noqa: BLE001
                raise ApiError(400, "image_base64 is not valid base64")
            if len(raw) > MAX_IMAGE_BYTES:
                raise ApiError(413, "image larger than 4 MB")
            mt = str(body.get("media_type") or "image/jpeg")
            if mt not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
                raise ApiError(400, "media_type must be image/jpeg, image/png, image/webp or image/gif")
        if not text and not image_b64 and not button_id:
            raise ApiError(400, "send text, image_base64 or button_id")
        session = re.sub(r"[^A-Za-z0-9_-]", "", str(body.get("session_id") or client_id))[:64] or "anon"
        payload = {"member": member, "text": text, "button_id": button_id, "image_base64": image_b64,
                   "media_type": body.get("media_type") or "image/jpeg", "session": session}
        return self.deferrer.run("chat", payload)

    def _run_chat(self, p: dict) -> dict:
        app = self.app()
        agent = self.agent(app)
        member: Member = app.hh.member(p["member"])
        if p.get("button_id"):
            reply = agent.handle_button(member.phone, p["button_id"])
        else:
            image = base64.b64decode(p["image_base64"].split(",", 1)[-1]) if p.get("image_base64") else None
            reply = agent.handle_message(member.phone, p.get("text") or None, image,
                                         p.get("media_type") if image else None, channel="web",
                                         input_type="image" if image else "text",
                                         session_key=f"web:{member.id}:{p['session']}")
        out: dict = {"reply_text": reply.text, "buttons": reply.buttons, "member": member.display,
                     "notifications": [{"to_member": n.to_member, "text": n.text, "buttons": n.buttons}
                                       for n in reply.notifications]}
        if reply.order_ids:
            o = app.get_order(reply.order_ids[-1])
            if o:
                out["order"] = self.format_order(app, o)
                out["decisions"] = self.decisions_for(app, o["order_id"])
        return out

    # ---------- rules ----------
    def rules_draft(self, body: dict) -> dict:
        text = str(body.get("text") or "").strip()
        if not text:
            raise ApiError(400, "text is required")
        if len(text) > MAX_TEXT:
            raise ApiError(400, f"text longer than {MAX_TEXT} characters")
        return self.deferrer.run("rules_draft", {"text": text})

    def rules_activate(self, body: dict) -> dict:
        cedar = str(body.get("cedar") or "")
        title = str(body.get("title") or "").strip()
        if not cedar.strip() or not title:
            raise ApiError(400, "cedar and title are required")
        res = rules_mod.activate(self.repo, cedar, title, self.now(), str(body.get("title_hinglish") or ""),
                                 str(body.get("explanation_en") or ""))
        if not res["ok"]:
            raise ApiError(422, "; ".join(res["validation"]["errors"]) or "invalid policy")
        r = res["rule"]
        self.app().audit.log("rule_activated", actor="console", rule_id=r["id"], title=r["title"], cedar=r["cedar"])
        return {"ok": True, "rule": {"id": r["id"], "title_en": r["title"], "title_hinglish": r["title_hinglish"],
                                     "cedar": r["cedar"], "source": "custom", "active": True,
                                     "created_at": r["created_at"]}}

    def rules_delete(self, rule_id: str) -> dict:
        r = rules_mod.deactivate(self.repo, rule_id, self.now())
        if not r:
            raise ApiError(404, f"no custom rule {rule_id}")
        self.app().audit.log("rule_deactivated", actor="console", rule_id=rule_id, title=r["title"])
        return {"ok": True, "rule": {"id": r["id"], "title_en": r["title"], "source": "custom", "active": False}}

    # ---------- red team ----------
    def redteam(self, body: dict) -> dict:
        attack = str(body.get("attack") or "")
        if attack not in ATTACKS:
            raise ApiError(400, f"attack must be one of {', '.join(ATTACKS)}")
        app = self.app()
        res = run_attack(app, attack)
        app.audit.log("redteam_run", actor="console", attack=attack, verdict=res["verdict"], sandbox=True,
                      simulated_compromised_model=True,
                      policy_ids=sorted({p for d in res["decisions"] if not d["allowed"] for p in d["policy_ids"]}))
        return res

    # ---------- weekly refill ----------
    def admin_phone(self, app: Jhola) -> str:
        return self._admin_phone or app.hh.admins()[0].phone

    def last_inbound(self, phone: str) -> int | None:
        """Unix time of the admin's last WhatsApp message (starts the 24-hour window)."""
        doc = self.repo.get("wa_last_inbound", phone)
        if doc:
            return int(doc["at"])
        from datetime import datetime

        # Fallback for messages before tracking existed: WhatsApp conversation history (not web sessions).
        ts = [s["updated_at"] for s in self.repo.list("sessions")
              if s.get("updated_at") and not str(s.get("key", "")).startswith("web:")]
        return int(max(datetime.fromisoformat(t).timestamp() for t in ts)) if ts else None

    def refill_run(self, body: dict) -> dict:
        return self.deferrer.run("refill", {"send": bool(body.get("send", True))})

    def _run_refill(self, p: dict) -> dict:
        app = self.app()
        send = p.get("send", True)
        phone = self.admin_phone(app)
        if send:
            last = self.last_inbound(phone)
            if last is None or time.time() - last > WINDOW_S:
                app.audit.log("refill_skipped", actor="scheduler", reason="outside WhatsApp 24-hour window",
                              last_inbound_at=last)
                return {"sent": False, "skipped": "outside the WhatsApp 24-hour window (no approved template)",
                        "last_inbound_at": last}
        agent = self.agent(app)
        try:
            reply = agent.run_weekly_refill(session_key=None if send else "web:refill-preview",
                                            channel="whatsapp" if send else "web")
            model = "bedrock"
        except Exception as e:  # noqa: BLE001  deterministic fallback keeps the Sunday job alive
            from .scenarios import script_d
            from .stub_model import ScriptedModel

            app.audit.log("refill_model_failed", actor="scheduler", error=str(e)[:300])
            reply = agent.run_weekly_refill(model=ScriptedModel(script_d), channel="whatsapp" if send else "web")
            model = "scripted-fallback"
        out = {"reply_text": reply.text, "buttons": reply.buttons, "sent": False, "model": model}
        if reply.order_ids:
            o = app.get_order(reply.order_ids[-1])
            if o:
                out["order"] = self.format_order(app, o)
        if send and self.sender:
            out["message_ids"] = self.sender(phone, reply.text, reply.buttons)
            out["sent"] = True
            app.audit.log("refill_proposed", out.get("order", {}).get("order_id"), actor="scheduler",
                          channel="whatsapp")
        return out

    # ---------- demo reset ----------
    def demo_reset(self) -> dict:
        from .whatsapp import reset_demo

        reset_demo(self.repo)  # orders, txns, purchases, mandate, sessions; never demo_acting (persona)
        for c in ("audit", "web_jobs"):
            self.repo.delete_collection(c)
        app = self.app()  # recreates the mandate at the seeded usage
        app.audit.log("demo_reset", actor="console")
        return {"ok": True, "mandate_used_inr": app.month_spent()}

    # ---------- jobs ----------
    def execute_job(self, kind: str, payload: dict) -> dict:
        if kind == "chat":
            return self._run_chat(payload)
        if kind == "rules_draft":
            return rules_mod.draft_rule(payload["text"], self.llm)
        if kind == "refill":
            return self._run_refill(payload)
        raise ApiError(400, f"unknown job {kind}")


def new_job_id() -> str:
    return uuid.uuid4().hex[:16]
