"""Test harness: a WhatsApp channel wired to real Jhola services with a scripted model and a fake transport."""

import itertools
import json

from jhola.agent import JholaAgent
from jhola.config import DEMO_NOW, Clock
from jhola.orders import Jhola, shared_catalog
from jhola.scenarios import compose_reply
from jhola.store import InMemoryRepository
from jhola.stub_model import Call, Say, ScriptedModel
from jhola.vision import FixtureVisionReader
from jhola.whatsapp import MemoryDedupe, WhatsAppChannel, parse_sns_event

_wamid = itertools.count(1)

RULE_DRAFT = """<title>No chocolate for {member}</title>
<cedar>
@reason("{member} cannot order chocolate.")
@hinglish("{member} chocolate order nahi kar sakta.")
forbid (principal == Member::"{member}", action == Action::"purchase_item", resource)
when {{ resource.tags.contains("chocolate") }};
</cedar>
<explanation_en>{member} cannot order anything tagged chocolate.</explanation_en>
<explanation_hinglish>{member} chocolate order nahi kar sakta.</explanation_hinglish>
<tests>
[{{"case": "{member} buys chocolate", "member": "{member}", "action": "purchase_item",
   "product": {{"category": "snacks", "tags": ["chocolate"], "price_inr": 50}}, "quantity": 1, "expected": "deny"}},
 {{"case": "{member} buys chips", "member": "{member}", "action": "purchase_item",
   "product": {{"category": "snacks", "tags": ["chips"], "price_inr": 20}}, "quantity": 1, "expected": "allow"}}]
</tests>"""


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
        return "do packet doodh", "hi-IN"


class Scripts:
    """model_factory handing out the next scripted model."""

    def __init__(self):
        self.queue = []

    def __call__(self):
        return ScriptedModel(self.queue.pop(0))


class World:
    def __init__(self, repo=None, clock=None, demo=()):
        self.repo = repo if repo is not None else InMemoryRepository()
        self.clock = clock or Clock(DEMO_NOW)
        self.t = FakeTransport()
        self.scripts = Scripts()
        self.llm_member = "aarav"
        self.ch = WhatsAppChannel(self.repo, self.t, MemoryDedupe(), self.agent, demo=set(demo), clock=self.clock)

    def llm(self, system, user):
        return RULE_DRAFT.format(member=self.llm_member)

    def app(self, hid):
        return Jhola(self.repo, self.clock, household_id=hid)

    def agent(self, hid):
        return JholaAgent(self.app(hid), self.scripts, FixtureVisionReader(), llm=self.llm)

    # ----- inbound -----
    def _in(self, message):
        entry = {"changes": [{"value": {"messages": [message]}}]}
        ev = {"Records": [{"Sns": {"Message": json.dumps({"whatsAppWebhookEntry": json.dumps(entry)})}}]}
        before = len(self.t.payloads)
        for m in parse_sns_event(ev):
            self.ch.handle(m)
        return self.t.payloads[before:]

    def say(self, phone, text, script=None):
        if script:
            self.scripts.queue.append(script)
        return self._in({"from": phone.lstrip("+"), "id": f"wamid.{next(_wamid)}", "type": "text",
                         "text": {"body": text}})

    def tap(self, phone, button_id):
        return self._in({"from": phone.lstrip("+"), "id": f"wamid.{next(_wamid)}", "type": "interactive",
                         "interactive": {"type": "button_reply", "button_reply": {"id": button_id, "title": "x"}}})

    def onboard(self, phone, name="Priya, Sharma home", budget="5000", threshold="1000"):
        self.say(phone, "hi")
        self.say(phone, name)
        self.say(phone, budget)
        self.say(phone, threshold)
        return self.ch.dir.lookup(phone)["household_id"]

    def add_member(self, admin_phone, **args):
        out = self.say(admin_phone, "add member", propose("propose_add_member", args))
        return self.tap(admin_phone, button_ids(out[-1])[0])


def body(p):
    return p["text"]["body"] if p["type"] == "text" else p["interactive"]["body"]["text"]


def button_ids(p):
    return [b["reply"]["id"] for b in p["interactive"]["action"]["buttons"]]


def to(payloads, phone):
    return [p for p in payloads if p["to"] == phone]


def propose(tool, args):
    def script():
        yield Call(tool, args)
        yield Say("Please confirm.")
    return script


def order(sku, qty=1):
    def script():
        cart = yield Call("build_cart", {"items": [{"sku": sku, "qty": qty}]})
        res = yield Call("submit_order", {"order_id": cart[0]["order_id"]})
        yield Say(compose_reply(res[0]))
    return script


def order_word(word):
    def script():
        r = yield Call("resolve_item", {"query": word})
        cart = yield Call("build_cart", {"items": [{"sku": r[0]["sku"], "qty": r[0]["qty"]}]})
        res = yield Call("submit_order", {"order_id": cart[0]["order_id"]})
        yield Say(compose_reply(res[0]))
    return script


def staple_between(lo, hi):
    """A well-rated in-stock staple priced in (lo, hi], so tests do not depend on one SKU."""
    return next(i for i in shared_catalog().items if i["category"] == "staples" and i["in_stock"]
                and i["seller_rating"] >= 4.0 and lo < i["price_inr"] <= hi)
