"""WhatsApp channel adapter (AWS End User Messaging Social).

Inbound: SNS notification -> whatsAppWebhookEntry (Meta webhook entry JSON) -> messages[].
Text, parchi photos (media via S3) and voice notes (Amazon Transcribe, hi-IN / en-IN) are handled.
Outbound: socialmessaging SendWhatsAppMessage with raw Meta message JSON.

DEMO FEATURE (persona switch): one real phone can act as any household member, so the whole
family flow can be shown from a single WhatsApp number. For phones listed in JHOLA_DEMO_PHONES:
  /as mom | /as dad | /as didi | /as teen   act as that member (persisted per phone)
  /whoami                                   show the acting member
  /reset                                    reset demo state (mandate usage, orders, history)
  /help                                     list commands
Messages addressed to members whose phone is a placeholder (not a real WhatsApp number) are
delivered to the demo phones instead, labelled with the member's name.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from . import config
from .store import Repository

log = logging.getLogger("jhola.whatsapp")

META_API_VERSION = "v20.0"
PLACEHOLDER_PREFIX = "+9199999"  # demo household members without a real phone
PERSONAS = {"mom": "mom", "dad": "dad", "didi": "didi", "teen": "teen", "aarav": "teen"}
MAX_TEXT = 4000
MAX_BUTTON_BODY = 1000

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U0000FE0F\U0000200D\U00002B00-\U00002BFF]"
)

HELP = (
    "*Jhola demo commands*\n"
    "/as mom, /as dad, /as didi, /as teen - act as that family member\n"
    "/whoami - who you are acting as\n"
    "/reset - reset demo orders and mandate\n"
    "Then send a grocery list, a parchi photo, or a dish like 'rajma chawal for 6'."
)


def demo_phones() -> set[str]:
    raw = os.environ.get("JHOLA_DEMO_PHONES")
    if raw is None:
        raw = config.ADMIN_PHONE if not config.ADMIN_PHONE.startswith(PLACEHOLDER_PREFIX) else ""
    return {normalize_phone(p) for p in raw.split(",") if p.strip()}


def normalize_phone(p: str) -> str:
    digits = re.sub(r"[^0-9]", "", p or "")
    return f"+{digits}" if digits else ""


# ---------- formatting ----------
def format_text(text: str) -> str:
    """Model output -> WhatsApp text: *bold*, no markdown headings/tables, no emojis."""
    t = EMOJI_RE.sub("", text or "")
    t = re.sub(r"\*\*(.+?)\*\*", r"*\1*", t)
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
    """Routes one inbound WhatsApp message through the Jhola agent and sends the replies.

    agent_factory() must return a fresh JholaAgent (built per message so counters and state
    are re-read from the repository).
    """

    def __init__(self, repo: Repository, transport: Transport, dedupe: Dedupe,
                 agent_factory: Callable[[], Any], demo: set[str] | None = None) -> None:
        self.repo = repo
        self.t = transport
        self.dedupe = dedupe
        self.agent_factory = agent_factory
        self.demo = demo_phones() if demo is None else demo
        self.sent: list[dict] = []

    # ----- outbound -----
    def _send(self, to: str, text: str, buttons: list[dict] | None = None) -> None:
        for p in outbound_payloads(to, text, buttons):
            try:
                mid = self.t.send(p)
                self.sent.append({"to": to, "type": p["type"], "message_id": mid})
                log.info("whatsapp_sent", extra={"to": to, "type": p["type"], "message_id": mid})
            except Exception as e:  # noqa: BLE001
                log.error("whatsapp_send_failed", extra={"to": to, "error": str(e)})

    def _deliver_notification(self, n, sender: str) -> None:
        """Send to the member's real phone; placeholder phones go to the demo phone(s), labelled."""
        to = normalize_phone(n.to_phone)
        if to and not to.startswith(PLACEHOLDER_PREFIX):
            self._send(to, n.text, n.buttons)
            return
        targets = self.demo or {sender}
        label = n.to_member.capitalize()
        for d in targets:
            self._send(d, f"[Demo: message for {label}]\n{n.text}", n.buttons)

    def _voice_reply(self, to: str, text: str) -> None:
        """Optional spoken summary after a voice note (JHOLA_VOICE_REPLY=1)."""
        if os.environ.get("JHOLA_VOICE_REPLY") != "1" or not hasattr(self.t, "send_voice"):
            return
        try:
            mid = self.t.send_voice(to, spoken_summary(text))
            self.sent.append({"to": to, "type": "audio", "message_id": mid})
            log.info("whatsapp_sent", extra={"to": to, "type": "audio", "message_id": mid})
        except Exception as e:  # noqa: BLE001
            log.error("voice_reply_failed", extra={"to": to, "error": str(e)})

    def _deliver(self, sender: str, reply) -> None:
        self._send(sender, reply.text, reply.buttons)
        for n in reply.notifications:
            self._deliver_notification(n, sender)

    # ----- demo persona -----
    def acting_member(self, agent, phone: str):
        """Member this phone speaks as: the demo persona if set, else the member owning the phone."""
        if phone in self.demo:
            doc = self.repo.get("demo_acting", phone)
            if doc:
                return agent.app.hh.member(doc["member_id"])
        return agent.app.hh.member_by_phone(phone)

    def _command(self, agent, msg: Inbound) -> str | None:
        text = (msg.text or "").strip()
        if not text.startswith("/") or msg.phone not in self.demo:
            return None
        cmd, _, arg = text[1:].partition(" ")
        cmd, arg = cmd.lower(), arg.strip().lower()
        if cmd == "as":
            mid = PERSONAS.get(arg)
            if not mid:
                return "Use: /as mom, /as dad, /as didi or /as teen"
            self.repo.put("demo_acting", msg.phone, {"member_id": mid})
            m = agent.app.hh.member(mid)
            agent.app.audit.log("demo_persona_set", actor=msg.phone, member=mid)
            return f"Demo: ab aap *{m.display}* ({m.role}) ki taraf se baat kar rahe hain."
        if cmd == "whoami":
            m = self.acting_member(agent, msg.phone)
            return f"Demo: aap *{m.display}* ({m.role}) hain." if m else "Demo: koi member set nahi hai."
        if cmd == "reset":
            reset_demo(self.repo)
            return "Demo reset: orders, payments aur history saaf. Mandate wapas Rs 5000 cap, Rs 1850 used."
        if cmd in ("help", "start"):
            return HELP
        return None

    # ----- main entry -----
    def handle(self, msg: Inbound) -> None:
        if not msg.wamid or not self.dedupe.first_time(msg.wamid):
            log.info("duplicate_skipped", extra={"wamid": msg.wamid})
            return
        log.info("inbound", extra={"wamid": msg.wamid, "from": msg.phone, "kind": msg.kind})
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

    def _handle(self, msg: Inbound) -> None:
        agent = self.agent_factory()
        reply_cmd = self._command(agent, msg)
        if reply_cmd is not None:
            self._send(msg.phone, reply_cmd)
            return
        member = self.acting_member(agent, msg.phone)
        if member is None:
            self._send(msg.phone, "Sorry, this number is not part of a Jhola household.")
            return
        if msg.kind == "button" and msg.button_id:
            kind = msg.button_id.split(":", 1)[0]
            if kind in ("approve", "reject"):
                # Approvals are signed off by whoever owns the real phone (the admin), whatever the persona.
                reply = agent.handle_button(msg.phone, msg.button_id)
            else:
                reply = agent.handle_button(member.phone, msg.button_id)
        elif msg.kind == "audio":
            text, lang = self.t.transcribe(msg.media_id)
            agent.app.audit.log("voice_transcribed", actor=member.id, transcript=text, language=lang,
                                media_type=msg.media_type)
            log.info("voice_transcribed", extra={"wamid": msg.wamid, "language": lang, "chars": len(text)})
            if not text:
                self._send(msg.phone, "Voice note samajh nahi aaya. Ek baar phir boliye ya type karke bhejiye.")
                return
            reply = agent.handle_message(member.phone, f"(voice note) {text}", input_type="voice")
            self._deliver(msg.phone, reply)
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
        self._deliver(msg.phone, reply)


def reset_demo(repo: Repository) -> None:
    for c in ("orders", "txns", "purchases", "mandate", "sessions"):
        repo.delete_collection(c)
