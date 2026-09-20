"""WhatsApp channel adapter (AWS End User Messaging Social).

Inbound: SNS notification -> whatsAppWebhookEntry (Meta webhook entry JSON) -> messages[].
Text, parchi photos (media via S3) and voice notes (Amazon Transcribe, hi-IN / en-IN) are handled.
Outbound: socialmessaging SendWhatsAppMessage with raw Meta message JSON.

Identity is the sender's phone number: the directory maps it to (household, member). A number Jhola
has never seen is onboarded in the chat (onboarding.py) and becomes the admin of a new household; a
number an admin invited is recognised and greeted by name on its first message.

WhatsApp only allows free-form messages within 24 hours of the recipient's last message. An approval
request for an admin outside that window stays pending: the requester is told, and the admin gets it
first thing when they next message Jhola.

DEMO FEATURE (persona switch), only for phones flagged demo=true in the directory (the owner, seeded
from JHOLA_DEMO_PHONES) and hidden from /help for everyone else: one real phone acts as any member of
the seeded Gupta family (household demo-gupta).
  /as mom | /as dad | /as didi | /as teen | /as dadi   act as that member (persisted per phone)
  /whoami                                   show the acting member
  /reset                                    reset demo state (mandate usage, orders, history)
Messages for demo members whose phone is a placeholder are delivered to the demo phones, labelled.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .domain import DEMO_HOUSEHOLD_ID
from .household import SYSTEM_HOUSEHOLD, Directory, demo_phones_from_env
from .phones import mask_phone, to_e164
from .store import Repository, ScopedRepository

log = logging.getLogger("jhola.whatsapp")

META_API_VERSION = "v20.0"
PLACEHOLDER_PREFIX = "+9199999"  # demo household members without a real phone
PERSONAS = {"mom": "mom", "dad": "dad", "didi": "didi", "teen": "teen", "aarav": "teen", "dadi": "dadi"}
MAX_TEXT = 4000
MAX_BUTTON_BODY = 1000

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U0000FE0F\U0000200D\U00002B00-\U00002BFF]"
)

WINDOW_S = 24 * 3600 - 300  # WhatsApp customer-service window, with a 5 minute margin
REAL_PHONE_BUTTONS = ("approve", "reject", "confirm", "cancel", "topup", "leave")
GREETINGS = {"hi", "hello", "hey", "hii", "namaste", "namaskar", "start", "hello jhola", "hi jhola"}
LEAVE_RE = re.compile(r"^\s*(please\s+)?(delete (all )?my data|leave( jhola| household)?|forget me|"
                      r"mera data (delete|hata)( kar)?( do| dijiye)?|remove me)\s*[.!]*\s*$", re.I)

DEMO_HELP = (
    "*Jhola demo commands*\n"
    "/as mom, /as dad, /as didi, /as teen, /as dadi - act as that family member\n"
    "/whoami - who you are acting as\n"
    "/reset - reset demo orders and mandate\n"
    "Then send a grocery list, a parchi photo, or a dish like 'rajma chawal for 6'."
)
HELP = (
    "*Jhola*\n"
    "- Send a grocery list as text, a voice note, or a photo of a handwritten list.\n"
    "- Ask for a dish (\"rajma chawal for 6\") or \"the usual\". Your brands are remembered.\n"
    "- \"delete my data\" removes you from Jhola.\n"
    "Payments are SIMULATED."
)
ADMIN_HELP = (
    "\n*Admin*\n"
    "- \"Add Sunita didi 98765 43210, groceries only, 500 a day\"\n"
    "- \"List members\", \"Remove Sunita\", \"Change Aarav's limit to 300 a day\"\n"
    "- \"No chocolate for Aarav\", \"Show my rules\", \"Remove rule 2\"\n"
    "- \"Didi can spend 1500 this week\", \"Change budget to 8000\", \"This month's spending\"\n"
    "Every change asks you Yes / No first."
)


def demo_phones() -> set[str]:
    return demo_phones_from_env()


def normalize_phone(p: str) -> str:
    """Inbound WhatsApp ids are digits with the country code; anything else is normalized to +91."""
    digits = re.sub(r"[^0-9]", "", p or "")
    if len(digits) > 10 and not digits.startswith("0"):
        return f"+{digits}"
    return to_e164(p)


# ---------- formatting ----------
def format_text(text: str) -> str:
    """Model output -> WhatsApp text: *bold*, no markdown headings/tables, no emojis."""
    t = EMOJI_RE.sub("", text or "")
    t = re.sub(r"\*\*([^*\n]+?)\*\*", r"*\1*", t)  # never eats a masked phone like +91******3210
    t = re.sub(r"__(.+?)__", r"_\1_", t)
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*\|?\s*:?-{3,}.*$", "", t, flags=re.M)
    t = re.sub(r"`{1,3}", "", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t[:MAX_TEXT] or "..."


def spoken_summary(text: str, limit: int = 300) -> str:
    """Reply text -> a short line to speak: drop item lists and markup, keep the first sentences."""
    lines = [l.strip() for l in format_text(text).replace("*", "").splitlines()]
    prose = " ".join(l for l in lines if l and not l.startswith("-"))
    if len(prose) <= limit:
        return prose or "Aapka order process ho gaya hai."
    cut = prose[:limit]
    return cut[: max(cut.rfind(". "), cut.rfind("? "), 80) + 1].strip()


def text_payload(to: str, body: str) -> dict:
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "text",
            "text": {"preview_url": False, "body": format_text(body)}}


def buttons_payload(to: str, body: str, buttons: list[dict]) -> dict:
    return {
        "messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": format_text(body)[:MAX_BUTTON_BODY]},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": b["id"][:256], "title": b["title"][:20]}} for b in buttons[:3]
            ]},
        },
    }


def outbound_payloads(to: str, text: str, buttons: list[dict] | None) -> list[dict]:
    if not buttons:
        return [text_payload(to, text)]
    body = format_text(text)
    if len(body) <= MAX_BUTTON_BODY:
        return [buttons_payload(to, body, buttons)]
    return [text_payload(to, body), buttons_payload(to, "Kya karein?", buttons)]


# ---------- inbound parsing ----------
@dataclass
class Inbound:
    wamid: str
    phone: str
    kind: str  # text | image | audio | button | unsupported
    text: str | None = None
    media_id: str | None = None
    media_type: str | None = None
    button_id: str | None = None


def parse_sns_event(event: dict) -> list[Inbound]:
    out = []
    for rec in event.get("Records", []):
        msg = rec.get("Sns", {}).get("Message") or "{}"
        out.extend(parse_notification(json.loads(msg)))
    return out


def parse_notification(msg: dict) -> list[Inbound]:
    raw = msg.get("whatsAppWebhookEntry")
    if not raw:
        return []
    entry = json.loads(raw) if isinstance(raw, str) else raw
    out = []
    for ch in entry.get("changes", []):
        for m in ch.get("value", {}).get("messages", []) or []:
            out.append(parse_message(m))
    return out


def parse_message(m: dict) -> Inbound:
    t = m.get("type")
    base = {"wamid": m.get("id", ""), "phone": normalize_phone(m.get("from", ""))}
    if t == "text":
        return Inbound(kind="text", text=m.get("text", {}).get("body", ""), **base)
    if t == "image":
        img = m.get("image", {})
        return Inbound(kind="image", text=img.get("caption"), media_id=img.get("id"),
                       media_type=img.get("mime_type", "image/jpeg"), **base)
    if t == "audio":  # voice notes: audio/ogg; codecs=opus
        a = m.get("audio", {})
        return Inbound(kind="audio", media_id=a.get("id"), media_type=a.get("mime_type", "audio/ogg"), **base)
    if t == "interactive":
        it = m.get("interactive", {})
        rep = it.get("button_reply") or it.get("list_reply") or {}
        return Inbound(kind="button", button_id=rep.get("id"), text=rep.get("title"), **base)
    if t == "button":  # quick-reply button on a template message
        b = m.get("button", {})
        return Inbound(kind="button", button_id=b.get("payload"), text=b.get("text"), **base)
    return Inbound(kind="unsupported", text=t, **base)


# ---------- ports ----------
class Transport(Protocol):
    def send(self, payload: dict) -> str | None: ...
    def mark_read(self, wamid: str) -> None: ...
    def fetch_media(self, media_id: str) -> tuple[bytes, str | None]: ...
    def transcribe(self, media_id: str) -> tuple[str, str | None]: ...


def media_format(mime: str | None) -> str:
    """WhatsApp audio mime type -> Transcribe MediaFormat."""
    m = (mime or "audio/ogg").split(";")[0].strip().lower()
    return {"audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "mp4", "audio/aac": "mp4",
            "audio/amr": "amr", "audio/wav": "wav", "audio/webm": "webm"}.get(m, "ogg")


def transcribe_s3(bucket: str, key: str, fmt: str = "ogg", timeout_s: float = 45.0) -> tuple[str, str | None]:
    """Batch Amazon Transcribe job on an S3 object with language id limited to Hindi / Indian English."""
    import time
    import uuid

    import boto3

    tr = boto3.client("transcribe")
    s3 = boto3.client("s3")
    name = f"jhola-{uuid.uuid4().hex[:16]}"
    tr.start_transcription_job(
        TranscriptionJobName=name, Media={"MediaFileUri": f"s3://{bucket}/{key}"},
        MediaFormat=fmt,
        IdentifyLanguage=True, LanguageOptions=["hi-IN", "en-IN"],
        OutputBucketName=bucket, OutputKey=f"transcripts/{name}.json",
    )
    deadline = time.time() + timeout_s
    while True:
        job = tr.get_transcription_job(TranscriptionJobName=name)["TranscriptionJob"]
        st = job["TranscriptionJobStatus"]
        if st == "COMPLETED":
            break
        if st == "FAILED":
            raise RuntimeError(f"transcription failed: {job.get('FailureReason')}")
        if time.time() > deadline:
            raise TimeoutError("transcription timed out")
        time.sleep(1)
    out = json.loads(s3.get_object(Bucket=bucket, Key=f"transcripts/{name}.json")["Body"].read())
    text = " ".join(t["transcript"] for t in out["results"]["transcripts"]).strip()
    return text, job.get("LanguageCode")


class Dedupe(Protocol):
    def first_time(self, message_id: str) -> bool: ...


class AwsTransport:
    """socialmessaging + S3. The media bucket receives inbound images (7-day lifecycle)."""

    def __init__(self, phone_number_id: str, media_bucket: str, region: str | None = None) -> None:
        import boto3

        self.phone_number_id = phone_number_id
        self.bucket = media_bucket
        self.sm = boto3.client("socialmessaging", region_name=region)
        self.s3 = boto3.client("s3", region_name=region)

    def send(self, payload: dict) -> str | None:
        resp = self.sm.send_whatsapp_message(
            originationPhoneNumberId=self.phone_number_id, metaApiVersion=META_API_VERSION,
            message=json.dumps(payload, ensure_ascii=False).encode(),
        )
        return resp.get("messageId")

    def mark_read(self, wamid: str) -> None:
        """Blue ticks + typing indicator while the agent works (not a user-visible message)."""
        self.send({"messaging_product": "whatsapp", "status": "read", "message_id": wamid,
                   "typing_indicator": {"type": "text"}})

    def media_to_s3(self, media_id: str) -> tuple[str, str | None]:
        """Pull inbound media from WhatsApp into the media bucket; returns (key, mime type)."""
        # The service treats "key" as a prefix and writes <prefix><mediaId>.<ext>, so list it back.
        prefix = f"inbound/{media_id}/"
        resp = self.sm.get_whatsapp_message_media(
            mediaId=media_id, originationPhoneNumberId=self.phone_number_id,
            destinationS3File={"bucketName": self.bucket, "key": prefix},
        )
        objs = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix).get("Contents", [])
        if not objs:
            raise RuntimeError(f"media {media_id} not found in s3://{self.bucket}/{prefix}")
        return objs[0]["Key"], resp.get("mimeType")

    def fetch_media(self, media_id: str) -> tuple[bytes, str | None]:
        key, mime = self.media_to_s3(media_id)
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read(), mime

    def send_voice(self, to: str, text: str) -> str | None:
        """Short spoken reply: Polly Kajal (neural, hi-IN) -> ogg/opus -> WhatsApp media -> audio message."""
        import uuid

        import boto3

        audio = boto3.client("polly").synthesize_speech(
            Engine="neural", VoiceId="Kajal", LanguageCode="hi-IN", OutputFormat="ogg_opus", Text=text,
        )["AudioStream"].read()
        key = f"outbound/{uuid.uuid4().hex}.ogg"
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=audio, ContentType="audio/ogg")
        media_id = self.sm.post_whatsapp_message_media(
            originationPhoneNumberId=self.phone_number_id, sourceS3File={"bucketName": self.bucket, "key": key},
        )["mediaId"]
        return self.send({"messaging_product": "whatsapp", "recipient_type": "individual", "to": to,
                          "type": "audio", "audio": {"id": media_id}})

    def transcribe(self, media_id: str) -> tuple[str, str | None]:
        """Voice note -> (transcript, language code) with Amazon Transcribe (hi-IN / en-IN)."""
        key, mime = self.media_to_s3(media_id)
        return transcribe_s3(self.bucket, key, media_format(mime))


class DryRunTransport:
    """Records outbound messages instead of sending them (synthetic test events, see lambda_handler)."""

    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def send(self, payload: dict) -> str | None:
        self.payloads.append(payload)
        return f"dry-run-{len(self.payloads)}"

    def mark_read(self, wamid: str) -> None:
        pass

    def fetch_media(self, media_id: str) -> tuple[bytes, str | None]:
        raise RuntimeError("no media in a dry run")

    def transcribe(self, media_id: str) -> tuple[str, str | None]:
        raise RuntimeError("no media in a dry run")


class DynamoDedupe:
    """Conditional put on the WhatsApp message id; items expire via TTL."""

    def __init__(self, table_name: str, ttl_days: int = 7, region: str | None = None) -> None:
        import boto3

        self.table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        self.ttl = ttl_days * 86400

    def first_time(self, message_id: str) -> bool:
        import time

        from botocore.exceptions import ClientError

        try:
            self.table.put_item(
                Item={"id": message_id, "expires_at": int(time.time()) + self.ttl},
                ConditionExpression="attribute_not_exists(id)",
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise


class MemoryDedupe:
    def __init__(self) -> None:
        self.seen: set[str] = set()

    def first_time(self, message_id: str) -> bool:
        if message_id in self.seen:
            return False
        self.seen.add(message_id)
        return True


# ---------- the channel ----------
class WhatsAppChannel:
    """Routes one inbound WhatsApp message to the sender's household and sends the replies.

    agent_factory(household_id) must return a fresh JholaAgent for that household (built per message so
    counters and state are re-read from the repository).
    """

    def __init__(self, repo: Repository, transport: Transport, dedupe: Dedupe,
                 agent_factory: Callable[[str], Any], demo: set[str] | None = None, clock=None) -> None:
        self.repo = repo.base if isinstance(repo, ScopedRepository) else repo
        self.t = transport
        self.dedupe = dedupe
        self.agent_factory = agent_factory
        self.demo = demo_phones() if demo is None else demo
        self.dir = Directory(self.repo, clock)
        self._demo_ready = False
        self.sent: list[dict] = []

    # ----- outbound -----
    def _send(self, to: str, text: str, buttons: list[dict] | None = None) -> None:
        for p in outbound_payloads(to, text, buttons):
            try:
                mid = self.t.send(p)
                self.sent.append({"to": mask_phone(to), "type": p["type"], "message_id": mid})
                log.info("whatsapp_sent", extra={"to": mask_phone(to), "type": p["type"], "message_id": mid})
            except Exception as e:  # noqa: BLE001
                log.error("whatsapp_send_failed", extra={"to": mask_phone(to), "error": str(e)})

    def in_window(self, phone: str) -> bool:
        import time

        doc = self.repo.get("wa_last_inbound", phone)
        return bool(doc) and time.time() - int(doc["at"]) < WINDOW_S

    def _deliver_notification(self, n, sender: str, app) -> bool:
        """Send to the member's real phone if WhatsApp's 24-hour window is open (the sender's always is).
        Demo placeholder phones go to the demo phone(s), labelled. Returns True if anything was sent."""
        to = normalize_phone(n.to_phone)
        text = n.text
        if app.hh.demo and (not to or to.startswith(PLACEHOLDER_PREFIX)):
            targets = sorted(self.demo) or [sender]
            text = f"[Demo: message for {app.hh.display_of(n.to_member)}]\n{n.text}"
        else:
            targets = [to]
        delivered = []
        for target in targets:
            if target == sender or self.in_window(target):
                self._send(target, text, n.buttons)
                delivered.append(target)
            else:
                log.info("outside_24h_window", extra={"to": mask_phone(target), "kind": n.kind})
                app.audit.log("notification_held", n.order_id, actor="jhola", to=n.to_member, kind=n.kind,
                              reason="outside WhatsApp 24-hour window")
        if delivered and n.kind == "approval" and n.order_id:
            self._mark_delivered(app, n.order_id, [to] if to else delivered)
        return bool(delivered)

    @staticmethod
    def _mark_delivered(app, order_id: str, phones: list[str]) -> None:
        o = app.get_order(order_id)
        if o:
            o["approval_delivered"] = sorted(set(o.get("approval_delivered", [])) | set(phones))
            app.repo.put("orders", order_id, o)

    def _voice_reply(self, to: str, text: str) -> None:
        """Optional spoken summary after a voice note (JHOLA_VOICE_REPLY=1)."""
        if os.environ.get("JHOLA_VOICE_REPLY") != "1" or not hasattr(self.t, "send_voice"):
            return
        try:
            mid = self.t.send_voice(to, spoken_summary(text))
            self.sent.append({"to": mask_phone(to), "type": "audio", "message_id": mid})
            log.info("whatsapp_sent", extra={"to": mask_phone(to), "type": "audio", "message_id": mid})
        except Exception as e:  # noqa: BLE001
            log.error("voice_reply_failed", extra={"to": mask_phone(to), "error": str(e)})

    def _deliver(self, sender: str, reply, app) -> None:
        self._send(sender, reply.text, reply.buttons)
        held = False
        approvals = [n for n in reply.notifications if n.kind == "approval"]
        for n in reply.notifications:
            ok = self._deliver_notification(n, sender, app)
            held = held or (n.kind == "approval" and not ok)
        if approvals and held and not any(
                (app.get_order(n.order_id) or {}).get("approval_delivered") for n in approvals):
            who = app.hh.admin_label()
            self._send(sender, f"{who} ne pichhle 24 ghante mein Jhola ko message nahi kiya hai, isliye WhatsApp "
                               f"mujhe unhe approval request bhejne nahi deta. Unse kahiye Jhola ko ek \"hi\" "
                               f"bhej dein. Aapka order pending rahega aur unhe sabse pehle yahi dikhega.")

    def _surface_pending(self, app, phone: str) -> None:
        """An admin just messaged: show approvals that could not reach them, before anything else."""
        real = app.hh.member_by_phone(phone)
        if real is None or real.role != "admin":
            return
        for o in app.pending_approvals():
            if phone in o.get("approval_delivered", []):
                continue
            self._send(phone, "Pending approval:\n" + app.approval_text(o),
                       [{"id": f"approve:{o['order_id']}", "title": "Approve"},
                        {"id": f"reject:{o['order_id']}", "title": "Reject"}])
            self._mark_delivered(app, o["order_id"], [phone])
            app.audit.log("approval_surfaced", o["order_id"], actor="jhola", to=real.id)

    # ----- identity -----
    def _ensure_demo(self) -> None:
        if not self._demo_ready:
            self.dir.ensure_demo(self.demo)
            self._demo_ready = True

    def identify(self, phone: str) -> dict | None:
        idx = self.dir.lookup(phone)
        if not self._demo_ready and (idx is None or (phone in self.demo and not idx.get("demo"))):
            self._ensure_demo()  # first run: the demo household and the owner's flag may not exist yet
            idx = self.dir.lookup(phone)
        return idx

    def acting_member(self, agent, phone: str, idx: dict | None = None):
        """Member this phone speaks as: the demo persona if set (demo phones only), else its own member."""
        idx = idx if idx is not None else (self.dir.lookup(phone) or {})
        if idx.get("demo") and agent.app.hh.id == DEMO_HOUSEHOLD_ID:
            doc = self.repo.get("demo_acting", phone)
            if doc and agent.app.hh.find(doc["member_id"]):
                return agent.app.hh.find(doc["member_id"])
        return agent.app.hh.find(idx.get("member_id", "")) or agent.app.hh.member_by_phone(phone)

    def _command(self, agent, msg: Inbound, idx: dict) -> str | None:
        text = (msg.text or "").strip()
        if not text.startswith("/"):
            return None
        cmd, _, arg = text[1:].partition(" ")
        cmd, arg = cmd.lower(), arg.strip().lower()
        is_demo = bool(idx.get("demo")) and agent.app.hh.id == DEMO_HOUSEHOLD_ID
        if cmd in ("help", "start"):
            m = self.acting_member(agent, msg.phone, idx)
            return DEMO_HELP if is_demo else HELP + (ADMIN_HELP if m and m.role == "admin" else "")
        if not is_demo:
            return None  # /as, /whoami, /reset do not exist for ordinary phones
        if cmd == "as":
            mid = PERSONAS.get(arg)
            if not mid:
                return "Use: /as mom, /as dad, /as didi, /as teen or /as dadi"
            self.repo.put("demo_acting", msg.phone, {"member_id": mid})
            m = agent.app.hh.member(mid)
            agent.app.audit.log("demo_persona_set", actor=mask_phone(msg.phone), member=mid)
            return f"Demo: ab aap *{m.display}* ({m.role}) ki taraf se baat kar rahe hain."
        if cmd == "whoami":
            m = self.acting_member(agent, msg.phone, idx)
            return f"Demo: aap *{m.display}* ({m.role}) hain." if m else "Demo: koi member set nahi hai."
        if cmd == "reset":
            reset_demo(self.repo)
            return "Demo reset: orders, payments aur history saaf. Mandate wapas Rs 5000 cap, Rs 0 used."
        return None

    # ----- main entry -----
    def handle(self, msg: Inbound) -> None:
        if not msg.wamid or not self.dedupe.first_time(msg.wamid):
            log.info("duplicate_skipped", extra={"wamid": msg.wamid})
            return
        log.info("inbound", extra={"wamid": msg.wamid, "from": mask_phone(msg.phone), "kind": msg.kind})
        try:  # WhatsApp's 24-hour customer-service window starts at the user's last message
            import time

            self.repo.put("wa_last_inbound", msg.phone, {"phone": msg.phone, "at": int(time.time())})
        except Exception as e:  # noqa: BLE001
            log.warning("last_inbound_failed", extra={"error": str(e)})
        try:
            self.t.mark_read(msg.wamid)
        except Exception as e:  # noqa: BLE001
            log.warning("mark_read_failed", extra={"error": str(e)})
        try:
            self._handle(msg)
        except Exception as e:  # noqa: BLE001
            log.exception("handle_failed", extra={"wamid": msg.wamid, "error": str(e)})
            self._send(msg.phone, "Maaf kijiye, abhi kuch gadbad ho gayi. Thodi der mein phir try karein.")

    def _onboard(self, msg: Inbound) -> None:
        from .audit import AuditLog
        from .onboarding import Onboarding

        text = msg.text
        if msg.kind == "audio" and msg.media_id:
            text, _ = self.t.transcribe(msg.media_id)
        audit = AuditLog(self.dir.scoped(SYSTEM_HOUSEHOLD), self.dir.clock)
        r = Onboarding(self.dir, audit).handle(msg.phone, text, msg.button_id if msg.kind == "button" else None)
        if r.household_id:
            self.agent_factory(r.household_id).app.audit.log("household_created", actor="onboarding",
                                                             household_id=r.household_id)
        self._send(msg.phone, r.text, r.buttons)

    def _handle(self, msg: Inbound) -> None:
        idx = self.identify(msg.phone)
        if idx is None:
            self._onboard(msg)
            return
        agent = self.agent_factory(idx["household_id"])
        app = agent.app
        reply_cmd = self._command(agent, msg, idx)
        if reply_cmd is not None:
            self._send(msg.phone, reply_cmd)
            return
        member = self.acting_member(agent, msg.phone, idx)
        if member is None:  # stale index (the member was removed): start over as a new number
            self.repo.delete("phones", msg.phone)
            self._onboard(msg)
            return
        if self._privacy(app, msg, idx):
            return
        greeted = self._welcome(app, member, msg)
        self._surface_pending(app, msg.phone)
        if greeted and msg.kind == "text" and (msg.text or "").strip().lower().strip("!. ") in GREETINGS:
            return
        if msg.kind == "button" and msg.button_id:
            kind = msg.button_id.split(":", 1)[0]
            if kind in REAL_PHONE_BUTTONS:
                # Approvals and confirmations are signed by whoever owns the real phone, whatever the persona.
                reply = agent.handle_button(msg.phone, msg.button_id)
            else:
                reply = agent.handle_button(member.phone, msg.button_id)
        elif msg.kind == "audio":
            text, lang = self.t.transcribe(msg.media_id)
            app.audit.log("voice_transcribed", actor=member.id, transcript=text, language=lang,
                          media_type=msg.media_type)
            log.info("voice_transcribed", extra={"wamid": msg.wamid, "language": lang, "chars": len(text)})
            if not text:
                self._send(msg.phone, "Voice note samajh nahi aaya. Ek baar phir boliye ya type karke bhejiye.")
                return
            reply = agent.handle_message(member.phone, f"(voice note) {text}", input_type="voice")
            self._deliver(msg.phone, reply, app)
            self._voice_reply(msg.phone, reply.text)
            return
        elif msg.kind in ("text", "image"):
            image = media_type = None
            if msg.kind == "image":
                image, media_type = self.t.fetch_media(msg.media_id)
                media_type = (media_type or msg.media_type or "image/jpeg").split(";")[0]
            reply = agent.handle_message(member.phone, msg.text, image, media_type)
        else:
            self._send(msg.phone, "Abhi main text, voice note aur parchi photo samajh paata hoon.")
            return
        self._deliver(msg.phone, reply, app)

    # ----- invited members -----
    def _welcome(self, app, member, msg: Inbound) -> bool:
        """First message from a number the admin invited: greet by name and say what they can do."""
        if member.welcomed or normalize_phone(member.phone) != msg.phone:
            return False
        from .admin import limits_text
        from .onboarding import PRIVACY_URL

        member.welcomed = True
        app.directory.save_member(app.hh.id, member)
        app.audit.log("member_welcomed", actor=member.id)
        self._send(msg.phone,
                   f"Namaste {member.display}! {app.hh.admin_label()} ne aapko *{app.hh.name}* ke Jhola mein joda hai. "
                   f"Koi setup nahi chahiye.\n"
                   f"Aap order kar sakte hain: {limits_text(member, app.hh)}.\n"
                   f"List ki photo, voice note ya text bhejiye (\"2 doodh, atta\"). Payments SIMULATED hain.\n"
                   f"Privacy: {PRIVACY_URL} (\"delete my data\" kabhi bhi).")
        return True

    # ----- privacy -----
    def _privacy(self, app, msg: Inbound, idx: dict) -> bool:
        """"delete my data" / "leave": deterministic, confirmed with buttons, never routed through the model."""
        from .admin import leave_confirm, leave_prompt

        is_button = msg.kind == "button" and (msg.button_id or "").startswith("leave:")
        if not is_button and not (msg.kind == "text" and LEAVE_RE.match(msg.text or "")):
            return False
        me = app.hh.member_by_phone(msg.phone)
        if me is None or idx.get("demo"):
            self._send(msg.phone, "Yeh demo household hai. /reset se demo data saaf hota hai.")
            return True
        if not is_button:
            text, buttons = leave_prompt(app, me)
            self._send(msg.phone, text, buttons)
        elif msg.button_id == "leave:yes":
            self._send(msg.phone, leave_confirm(app, me))
        else:
            self._send(msg.phone, "Theek hai, kuch delete nahi hua.")
        return True


def reset_demo(repo: Repository) -> None:
    """Reset the demo household's orders, payments, history and learned brands (never another household)."""
    scoped = repo if isinstance(repo, ScopedRepository) and repo.household_id == DEMO_HOUSEHOLD_ID \
        else ScopedRepository(repo, DEMO_HOUSEHOLD_ID)
    for c in ("orders", "txns", "purchases", "mandate", "sessions", "pending_actions"):
        scoped.delete_collection(c)
    Directory(scoped.base).seed_demo_preferences()
