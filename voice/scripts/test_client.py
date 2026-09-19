"""Scripted WebSocket client: streams WAV files at real time and prints everything that comes back.

    uv run python scripts/test_client.py ws://localhost:8080 dad /tmp/jhola-voice/ask.wav /tmp/jhola-voice/order.wav

Writes the assistant audio to /tmp/jhola-voice/reply.wav (24 kHz PCM16).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import wave
from pathlib import Path

import websockets

CHUNK_MS = 32
IN_RATE = 16000
GAP_SECONDS = float(os.environ.get("JHOLA_VOICE_GAP", "14"))
TAIL_SECONDS = float(os.environ.get("JHOLA_VOICE_TAIL", "20"))
OUT_WAV = Path(os.environ.get("JHOLA_VOICE_REPLY", "/tmp/jhola-voice/reply.wav"))


def frames(path: str) -> bytes:
    with wave.open(path, "rb") as w:
        assert w.getframerate() == IN_RATE and w.getnchannels() == 1 and w.getsampwidth() == 2, "need 16k mono PCM16"
        return w.readframes(w.getnframes())


async def pump(ws, wavs: list[str]) -> None:
    chunk = IN_RATE * 2 * CHUNK_MS // 1000
    silence = b"\x00" * chunk
    for i, path in enumerate(wavs):
        if i:
            print(f"-- gap {GAP_SECONDS}s (listening) --", flush=True)
            for _ in range(int(GAP_SECONDS * 1000 / CHUNK_MS)):
                await ws.send(silence)
                await asyncio.sleep(CHUNK_MS / 1000)
        data = frames(path)
        print(f"-- speaking {Path(path).name} ({len(data) / (IN_RATE * 2):.1f}s) --", flush=True)
        for off in range(0, len(data), chunk):
            await ws.send(data[off:off + chunk].ljust(chunk, b"\x00"))
            await asyncio.sleep(CHUNK_MS / 1000)
    print(f"-- tail {TAIL_SECONDS}s (listening) --", flush=True)
    for _ in range(int(TAIL_SECONDS * 1000 / CHUNK_MS)):
        await ws.send(silence)
        await asyncio.sleep(CHUNK_MS / 1000)
    await ws.send(json.dumps({"type": "stop"}))


async def main() -> int:
    url, member = sys.argv[1], sys.argv[2]
    wavs = sys.argv[3:]
    audio_out = bytearray()
    events: list[dict] = []
    async with websockets.connect(url, origin="http://localhost:3000", max_size=2 ** 22) as ws:
        await ws.send(json.dumps({"type": "start", "member": member}))
        pumper = None
        t0 = time.time()
        async for raw in ws:
            if isinstance(raw, bytes):
                audio_out.extend(raw)
                continue
            msg = json.loads(raw)
            events.append(msg)
            kind = msg.get("type")
            if kind == "transcript":
                print(f"[{time.time() - t0:6.1f}s] {msg['role']}: {msg['text']}", flush=True)
            elif kind == "tool":
                extra = msg.get("args") if msg["phase"] == "start" else msg.get("summary", "")[:220]
                print(f"[{time.time() - t0:6.1f}s] tool {msg['name']} {msg['phase']}: {extra}", flush=True)
            elif kind in ("cart", "decisions", "order", "error", "ended", "ready", "interrupted", "model_closed"):
                print(f"[{time.time() - t0:6.1f}s] {kind}: {json.dumps(msg, ensure_ascii=False)[:400]}", flush=True)
            if kind == "ready" and pumper is None:
                pumper = asyncio.create_task(pump(ws, wavs))
            if kind == "ended":
                break
    if audio_out:
        OUT_WAV.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(OUT_WAV), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(bytes(audio_out))
        print(f"assistant audio: {OUT_WAV} ({len(audio_out) / 48000:.1f}s)")
    tools = [e["name"] for e in events if e.get("type") == "tool" and e.get("phase") == "start"]
    orders = [e for e in events if e.get("type") == "order"]
    print(f"tools called: {tools}")
    print(f"order events: {json.dumps(orders, ensure_ascii=False)[:600]}")
    return 0 if audio_out and tools else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
