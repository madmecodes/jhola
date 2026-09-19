"""WebSocket server: browser <-> Jhola voice assistant <-> Amazon Nova 2 Sonic.

Client -> server
  {"type":"start","member":"mom|dad|didi|teen","voice":"kiara|arjun"}   start a Sonic session
  binary frame                                                          16 kHz mono PCM16 mic audio
  {"type":"audio","data":"<base64 pcm16>"}                              same, for clients without binary
  {"type":"stop"}                                                       end the session

Server -> client
  binary frame                              24 kHz mono PCM16 assistant audio
  {"type":"ready","session_id","member","max_seconds","sample_rate_out"}
  {"type":"transcript","role":"user|assistant","text","stage"?}
  {"type":"interrupted"}                    barge-in: drop queued playback
  {"type":"tool","name","phase":"start|end","args"?,"summary"?}
  {"type":"cart","cart":{...}}              cart changed
  {"type":"decisions", ...}                 check_cart result (Cedar per-line decisions)
  {"type":"order", ...}                     checkout result
  {"type":"error","message"}
  {"type":"ended","reason"}
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
import uuid
from collections import defaultdict

import websockets
from websockets.asyncio.server import ServerConnection, serve
from websockets.http11 import Response

from .prompt import system_prompt
from .sonic import SonicSession
from .tools import MEMBERS, VoiceShop, sonic_tool_config

PORT = int(os.environ.get("PORT", "8080"))
MAX_SESSION_SECONDS = int(os.environ.get("JHOLA_VOICE_MAX_SECONDS", "300"))
MAX_PER_IP = int(os.environ.get("JHOLA_VOICE_MAX_PER_IP", "2"))
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "JHOLA_VOICE_ORIGINS", "https://jhola-phi.vercel.app,http://localhost:3000").split(",") if o.strip()]
VOICES = ("kiara", "arjun", "tiffany", "matthew")

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("jhola.voice")

_per_ip: dict[str, int] = defaultdict(int)


def client_ip(ws: ServerConnection) -> str:
    fwd = ws.request.headers.get("x-forwarded-for", "") if ws.request else ""
    if fwd:
        return fwd.split(",")[0].strip()
    return ws.remote_address[0] if ws.remote_address else "unknown"


class Connection:
    """One browser connection: at most one Sonic session at a time."""

    def __init__(self, ws: ServerConnection) -> None:
        self.ws = ws
        self.ip = client_ip(ws)
        self.session_id = uuid.uuid4().hex[:12]
        self.shop: VoiceShop | None = None
        self.sonic: SonicSession | None = None
        self.started_at = 0.0
        self.closing = False

    async def send_json(self, payload: dict) -> None:
        try:
            await self.ws.send(json.dumps(payload, ensure_ascii=False))
        except websockets.ConnectionClosed:
            pass

    async def send_audio(self, pcm: bytes) -> None:
        try:
            await self.ws.send(pcm)
        except websockets.ConnectionClosed:
            pass

    # ---------- tool bridge ----------
    async def on_tool(self, name: str, args: dict) -> dict:
        await self.send_json({"type": "tool", "name": name, "phase": "start", "args": args})
        assert self.shop
        result = await asyncio.to_thread(self.shop.call, name, args)
        log.info("tool %s %s -> %s", name, json.dumps(args)[:120], json.dumps(result, default=str)[:200])
        if name in ("add_to_cart", "remove_from_cart", "view_cart"):
            await self.send_json({"type": "cart", "cart": self.shop.cart_state()})
        elif name == "check_cart":
            await self.send_json({"type": "decisions", **result})
        elif name == "checkout":
            await self.send_json({"type": "order", **result})
            await self.send_json({"type": "cart", "cart": self.shop.cart_state()})
        await self.send_json({"type": "tool", "name": name, "phase": "end",
                              "summary": json.dumps(result, default=str, ensure_ascii=False)[:400]})
        return result

    # ---------- session ----------
    async def start_session(self, msg: dict) -> None:
        if self.sonic:
            await self.send_json({"type": "error", "message": "session already running"})
            return
        member = str(msg.get("member", "")).lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", member):
            await self.send_json({"type": "error", "message": f"member must be one of {', '.join(MEMBERS)}"})
            return
        voice = msg.get("voice") if msg.get("voice") in VOICES else "kiara"
        try:
            self.shop = await asyncio.to_thread(VoiceShop, member, self.session_id)
            self.sonic = SonicSession(system_prompt(self.shop), sonic_tool_config(),
                                      on_event=self.send_json, on_audio=self.send_audio,
                                      on_tool=self.on_tool, voice=voice)
            await self.sonic.start()
        except ValueError as e:  # unknown member for this household
            self.sonic = None
            await self.send_json({"type": "error", "message": str(e)[:200]})
            return
        except Exception as e:
            log.exception("session start failed")
            self.sonic = None
            await self.send_json({"type": "error", "message": f"could not start the voice model: {e}"[:300]})
            return
        self.started_at = time.time()
        await self.send_json({"type": "ready", "session_id": self.session_id, "member": member, "voice": voice,
                              "max_seconds": MAX_SESSION_SECONDS, "sample_rate_in": 16000, "sample_rate_out": 24000})
        await self.send_json({"type": "cart", "cart": self.shop.cart_state()})
        asyncio.create_task(self._watchdog())

    async def _watchdog(self) -> None:
        while self.sonic and self.sonic.active and not self.closing:
            if time.time() - self.started_at > MAX_SESSION_SECONDS:
                await self.send_json({"type": "ended", "reason": "session time limit reached"})
                await self.stop_session("time limit")
                return
            await asyncio.sleep(1)

    async def stop_session(self, reason: str) -> None:
        if self.sonic:
            await self.sonic.close()
            self.sonic = None
        await self.send_json({"type": "ended", "reason": reason})

    async def handle(self) -> None:
        async for raw in self.ws:
            if isinstance(raw, bytes):
                if self.sonic and self.sonic.active:
                    await self.sonic.send_audio(raw)
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                await self.send_json({"type": "error", "message": "invalid JSON"})
                continue
            kind = msg.get("type")
            if kind == "start":
                await self.start_session(msg)
            elif kind == "audio":
                if self.sonic and self.sonic.active:
                    await self.sonic.send_audio(base64.b64decode(msg.get("data", "")))
            elif kind == "stop":
                await self.stop_session("client stopped")
            elif kind == "ping":
                await self.send_json({"type": "pong"})
            else:
                await self.send_json({"type": "error", "message": f"unknown message type {kind}"})

    async def close(self) -> None:
        self.closing = True
        if self.sonic:
            await self.sonic.close()
            self.sonic = None


async def handler(ws: ServerConnection) -> None:
    conn = Connection(ws)
    ip = conn.ip
    if _per_ip[ip] >= MAX_PER_IP:
        await conn.send_json({"type": "error", "message": "too many voice sessions from this address"})
        await ws.close(1013, "too many sessions")
        return
    _per_ip[ip] += 1
    log.info("connect ip=%s session=%s", ip, conn.session_id)
    try:
        await conn.handle()
    except websockets.ConnectionClosed:
        pass
    except Exception:
        log.exception("connection error")
    finally:
        await conn.close()
        _per_ip[ip] -= 1
        if _per_ip[ip] <= 0:
            _per_ip.pop(ip, None)
        log.info("disconnect ip=%s session=%s", ip, conn.session_id)


def process_request(ws: ServerConnection, request) -> Response | None:
    """Health check for the load balancer, and the origin allow-list for browsers."""
    if request.path in ("/health", "/healthz"):
        return ws.respond(200, "ok\n")
    origin = request.headers.get("origin")
    if origin and ALLOWED_ORIGINS and origin not in ALLOWED_ORIGINS:
        log.warning("rejected origin %s", origin)
        return ws.respond(403, "origin not allowed\n")
    return None


async def main() -> None:
    log.info("jhola voice server on :%s origins=%s max_seconds=%s", PORT, ALLOWED_ORIGINS, MAX_SESSION_SECONDS)
    async with serve(handler, "0.0.0.0", PORT, process_request=process_request, max_size=2 ** 20,
                     ping_interval=20, ping_timeout=20):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
