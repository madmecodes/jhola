import json

from jhola.agent import Reply
from jhola.config import DEMO_NOW, Clock
from jhola.orders import Jhola, Outbound
from jhola.store import InMemoryRepository
from jhola.whatsapp import (
    MemoryDedupe, WhatsAppChannel, format_text, outbound_payloads, parse_sns_event,
)

OWNER = "+919999900001"  # Mom's phone in tests (JHOLA_ADMIN_PHONE default)


def sns(*messages):
    entry = {"id": "waba", "changes": [{"field": "messages", "value": {"messages": list(messages)}}]}
    body = {"messageId": "x", "whatsAppWebhookEntry": json.dumps(entry)}
    return {"Records": [{"Sns": {"Message": json.dumps(body)}}]}


def text_msg(body, wamid="wamid.1", frm="919999900001"):
    return {"from": frm, "id": wamid, "type": "text", "text": {"body": body}}


class FakeTransport:
    def __init__(self):
        self.payloads = []

    def send(self, payload):
        self.payloads.append(payload)
        return f"mid-{len(self.payloads)}"

    def mark_read(self, wamid):
        pass

    def fetch_media(self, media_id):
        return b"img", "image/jpeg"

    def transcribe(self, media_id):
        return "do packet doodh aur ek kilo atta", "hi-IN"


class FakeAgent:
    def __init__(self, app):
        self.app = app
        self.calls = []

    def handle_message(self, phone, text=None, image_bytes=None, media_type=None, **kw):
        self.calls.append(("msg", phone, text, image_bytes, media_type))
        n = [Outbound(OWNER, "mom", "Didi wants Rs 1179. Approve?",
                      [{"id": "approve:JH-1", "title": "Approve"}, {"id": "reject:JH-1", "title": "Reject"}])]
        return Reply("**Cart** ready 🛒", [], n)

    def handle_button(self, phone, button_id):
        self.calls.append(("button", phone, button_id))
        return Reply("Approved.", [], [Outbound("+919999900003", "didi", "Mom ne approve kar diya.")])


def make(demo=frozenset({OWNER})):
    repo = InMemoryRepository()
    app = Jhola(repo, Clock(DEMO_NOW))
    agent = FakeAgent(app)
    t = FakeTransport()
    ch = WhatsAppChannel(repo, t, MemoryDedupe(), lambda hid: agent, demo=set(demo))
    return ch, agent, t, repo


def test_parse_text_image_button():
    ev = sns(text_msg("atta"),
             {"from": "91999", "id": "w2", "type": "image", "image": {"id": "m1", "mime_type": "image/jpeg"}},
             {"from": "91999", "id": "w3", "type": "interactive",
              "interactive": {"type": "button_reply", "button_reply": {"id": "approve:JH-1", "title": "Approve"}}})
    a, b, c = parse_sns_event(ev)
    assert (a.kind, a.text, a.phone) == ("text", "atta", "+919999900001")
    assert (b.kind, b.media_id) == ("image", "m1")
    assert (c.kind, c.button_id) == ("button", "approve:JH-1")


def test_statuses_are_ignored():
    entry = {"changes": [{"value": {"statuses": [{"id": "s", "status": "delivered"}]}}]}
    ev = {"Records": [{"Sns": {"Message": json.dumps({"whatsAppWebhookEntry": json.dumps(entry)})}}]}
    assert parse_sns_event(ev) == []


def test_format_and_buttons():
    assert format_text("**Total** Rs 10 🛒\n## Done") == "*Total* Rs 10\nDone"
    [p] = outbound_payloads("+91x", "Approve?", [{"id": "approve:JH-1", "title": "Approve this order now please"}])
    assert p["type"] == "interactive"
    assert p["interactive"]["action"]["buttons"][0]["reply"]["title"] == "Approve this order now please"[:20]
    long = outbound_payloads("+91x", "x" * 1500, [{"id": "a", "title": "A"}])
    assert [p["type"] for p in long] == ["text", "interactive"]


def test_dedupe_skips_redelivery():
    ch, agent, t, _ = make()
    msg = parse_sns_event(sns(text_msg("atta")))[0]
    ch.handle(msg)
    ch.handle(msg)
    assert len([c for c in agent.calls if c[0] == "msg"]) == 1


def test_persona_switch_routes_as_member_and_approval_to_same_phone():
    ch, agent, t, repo = make()
    ch.handle(parse_sns_event(sns(text_msg("/as didi", "w1")))[0])
    assert "Didi" in t.payloads[-1]["text"]["body"]
    ch.handle(parse_sns_event(sns(text_msg("rajma chawal for 6", "w2")))[0])
    assert agent.calls[-1][1] == "+919999900003"  # spoke as Didi
    # reply to the owner phone + approval buttons to Mom, which is the same real phone
    assert [p["to"] for p in t.payloads[-2:]] == [OWNER, OWNER]
    assert t.payloads[-2]["text"]["body"] == "*Cart* ready"
    assert t.payloads[-1]["type"] == "interactive"


def test_approve_button_uses_real_phone_and_placeholder_notice_goes_to_demo_phone():
    ch, agent, t, repo = make()
    ch.handle(parse_sns_event(sns(text_msg("/as didi", "w1")))[0])
    btn = {"from": "919999900001", "id": "w3", "type": "interactive",
           "interactive": {"type": "button_reply", "button_reply": {"id": "approve:JH-1", "title": "Approve"}}}
    ch.handle(parse_sns_event(sns(btn))[0])
    assert agent.calls[-1] == ("button", OWNER, "approve:JH-1")
    assert t.payloads[-1]["to"] == OWNER
    assert t.payloads[-1]["text"]["body"].startswith("[Demo: message for Didi]")


def test_whoami_and_reset():
    ch, agent, t, repo = make()
    ch.handle(parse_sns_event(sns(text_msg("/whoami", "w1")))[0])
    assert "Mom" in t.payloads[-1]["text"]["body"]
    hh = agent.app.repo  # the demo household's scoped repository
    hh.put("orders", "JH-1", {"order_id": "JH-1"})
    assert hh.get("mandate", "MNDT-GUPTA-0001") is not None
    ch.handle(parse_sns_event(sns(text_msg("/reset", "w2")))[0])
    assert hh.list("orders") == [] and hh.get("mandate", "MNDT-GUPTA-0001") is None


def test_persona_commands_do_not_exist_for_ordinary_phones():
    ch, agent, t, repo = make(demo=frozenset())  # Mom's phone is a member but not flagged demo
    ch.handle(parse_sns_event(sns(text_msg("/as didi", "w1")))[0])
    assert repo.get("demo_acting", OWNER) is None
    assert agent.calls[-1][:3] == ("msg", OWNER, "/as didi")  # treated as an ordinary message from Mom
    ch.handle(parse_sns_event(sns(text_msg("/help", "w2")))[0])
    body = t.payloads[-1]["text"]["body"]
    assert "/as" not in body and "/reset" not in body and "Add Sunita" in body  # Mom is an admin


def test_unknown_sender_is_onboarded_not_rejected():
    ch, agent, t, repo = make(demo=frozenset())
    ch.handle(parse_sns_event(sns(text_msg("hi", "w1", frm="911234567890")))[0])
    body = t.payloads[-1]["text"]["body"]
    assert "1/3" in body and "jhola-phi.vercel.app/privacy" in body and "not part of" not in body
    assert agent.calls == []


def test_session_history_persists_in_repo():
    from jhola.agent import JholaAgent

    repo = InMemoryRepository()
    a = JholaAgent(Jhola(repo, Clock(DEMO_NOW)))
    msgs = [{"role": "user", "content": [{"text": "atta"}]},
            {"role": "assistant", "content": [{"reasoningContent": {"x": 1}}, {"text": "ok"}]}]
    a._save_session("+91x", msgs)
    assert a._load_session("+91x") == [{"role": "user", "content": [{"text": "atta"}]},
                                       {"role": "assistant", "content": [{"text": "ok"}]}]


def test_voice_note_is_transcribed_and_audited():
    ch, agent, t, repo = make()
    audio = {"from": "919999900001", "id": "w9", "type": "audio",
             "audio": {"id": "m9", "mime_type": "audio/ogg; codecs=opus", "voice": True}}
    ch.handle(parse_sns_event(sns(audio))[0])
    assert agent.calls[-1][:3] == ("msg", OWNER, "(voice note) do packet doodh aur ek kilo atta")
    ev = [e for e in agent.app.audit.events() if e["event"] == "voice_transcribed"][0]
    assert ev["data"]["language"] == "hi-IN" and "doodh" in ev["data"]["transcript"]


def test_media_format():
    from jhola.whatsapp import media_format
    assert media_format("audio/ogg; codecs=opus") == "ogg"
    assert media_format("audio/mpeg") == "mp3"


def test_spoken_summary_drops_lists():
    from jhola.whatsapp import spoken_summary
    s = spoken_summary("Order ready.\n- Atta x1\n- Doodh x2\n*Total: Rs 342*. Paid.")
    assert s == "Order ready. Total: Rs 342. Paid."


def test_lambda_dry_run_sends_nothing_and_returns_masked_payloads(monkeypatch):
    from jhola import lambda_handler as lh

    class NoSend:
        def send(self, payload):
            raise AssertionError("a dry run must never send")

    repo = InMemoryRepository()
    monkeypatch.setattr(lh, "_deps", lambda: (repo, NoSend(), MemoryDedupe()))
    ev = sns(text_msg("hello", "w-dry", frm="917000012345"))
    out = lh.handler({**ev, "jhola_dry_run": True}, None)
    [p] = out["dry_run_outbound"]
    assert p["to"] == "+91******2345" and "1/3" in p["text"]["body"]
    assert repo.get("onboarding", "+917000012345")["step"] == "name"
