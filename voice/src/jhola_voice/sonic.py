"""Amazon Nova 2 Sonic bidirectional stream session (InvokeModelWithBidirectionalStream).

Follows the event protocol of the official amazon-nova-samples speech-to-speech examples:
sessionStart -> promptStart (voice, tools) -> SYSTEM text content -> one interactive USER audio
content that stays open for the whole session. The model streams back contentStart / textOutput /
audioOutput / toolUse / contentEnd events; tool results go back as a TOOL content.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import uuid
from typing import Any, Awaitable, Callable

from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient, InvokeModelWithBidirectionalStreamOperationInput
from aws_sdk_bedrock_runtime.config import Config
from aws_sdk_bedrock_runtime.models import BidirectionalInputPayloadPart, InvokeModelWithBidirectionalStreamInputChunk

from .creds import REGION, RESOLVER

log = logging.getLogger("jhola.voice.sonic")

MODEL_ID = os.environ.get("JHOLA_SONIC_MODEL_ID", "amazon.nova-2-sonic-v1:0")
INPUT_RATE = 16000
OUTPUT_RATE = 24000

EventCb = Callable[[dict], Awaitable[None]]
AudioCb = Callable[[bytes], Awaitable[None]]
ToolCb = Callable[[str, dict], Awaitable[dict]]


def _client() -> BedrockRuntimeClient:
    return BedrockRuntimeClient(config=Config(
        endpoint_uri=f"https://bedrock-runtime.{REGION}.amazonaws.com", region=REGION,
        aws_credentials_identity_resolver=RESOLVER,
    ))


class SonicSession:
    def __init__(self, system_prompt: str, tool_config: dict, on_event: EventCb, on_audio: AudioCb,
                 on_tool: ToolCb, voice: str = "kiara", endpointing: str = "MEDIUM") -> None:
        self.system_prompt = system_prompt
        self.tool_config = tool_config
        self.on_event = on_event
        self.on_audio = on_audio
        self.on_tool = on_tool
        self.voice = voice
        self.endpointing = endpointing
        self.prompt = str(uuid.uuid4())
        self.audio_content = str(uuid.uuid4())
        self.stream = None
        self.active = False
        self._send_lock = asyncio.Lock()
        self._reader: asyncio.Task | None = None
        self._tool_tasks: set[asyncio.Task] = set()
        # per-content state
        self._role: dict[str, str] = {}
        self._stage: dict[str, str] = {}
        self._spoken: list[str] = []  # speculative assistant texts in the current turn
        self._tool_use: dict | None = None
        self.closed_reason = ""

    # ---------- send ----------
    async def _send(self, event: dict) -> None:
        if not self.active or not self.stream:
            return
        data = json.dumps({"event": event}).encode()
        chunk = InvokeModelWithBidirectionalStreamInputChunk(value=BidirectionalInputPayloadPart(bytes_=data))
        async with self._send_lock:
            await self.stream.input_stream.send(chunk)

    async def start(self) -> None:
        self.stream = await _client().invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=MODEL_ID))
        self.active = True
        p = self.prompt
        sys_name = str(uuid.uuid4())
        await self._send({"sessionStart": {
            "inferenceConfiguration": {"maxTokens": 1024, "topP": 0.9, "temperature": 0.6},
            "turnDetectionConfiguration": {"endpointingSensitivity": self.endpointing}}})
        await self._send({"promptStart": {
            "promptName": p,
            "textOutputConfiguration": {"mediaType": "text/plain"},
            "audioOutputConfiguration": {"mediaType": "audio/lpcm", "sampleRateHertz": OUTPUT_RATE,
                                         "sampleSizeBits": 16, "channelCount": 1, "voiceId": self.voice,
                                         "encoding": "base64", "audioType": "SPEECH"},
            "toolUseOutputConfiguration": {"mediaType": "application/json"},
            "toolConfiguration": self.tool_config}})
        await self._send({"contentStart": {"promptName": p, "contentName": sys_name, "type": "TEXT", "interactive": False,
                                           "role": "SYSTEM", "textInputConfiguration": {"mediaType": "text/plain"}}})
        await self._send({"textInput": {"promptName": p, "contentName": sys_name, "content": self.system_prompt}})
        await self._send({"contentEnd": {"promptName": p, "contentName": sys_name}})
        await self._send({"contentStart": {"promptName": p, "contentName": self.audio_content, "type": "AUDIO",
                                           "interactive": True, "role": "USER",
                                           "audioInputConfiguration": {"mediaType": "audio/lpcm",
                                                                       "sampleRateHertz": INPUT_RATE,
                                                                       "sampleSizeBits": 16, "channelCount": 1,
                                                                       "audioType": "SPEECH", "encoding": "base64"}}})
        self._reader = asyncio.create_task(self._read())

    async def send_audio(self, pcm16: bytes) -> None:
        if pcm16:
            await self._send({"audioInput": {"promptName": self.prompt, "contentName": self.audio_content,
                                             "content": base64.b64encode(pcm16).decode()}})

    async def close(self) -> None:
        if not self.active:
            return
        try:
            await self._send({"contentEnd": {"promptName": self.prompt, "contentName": self.audio_content}})
            await self._send({"promptEnd": {"promptName": self.prompt}})
            await self._send({"sessionEnd": {}})
            await self.stream.input_stream.close()
        except Exception as e:  # stream may already be gone
            log.info("close: %s", e)
        self.active = False
        for t in list(self._tool_tasks):
            t.cancel()
        if self._reader:
            self._reader.cancel()

    # ---------- receive ----------
    async def _read(self) -> None:
        try:
            while self.active:
                output = await self.stream.await_output()
                result = await output[1].receive()
                if not (result and result.value and result.value.bytes_):
                    continue
                msg = json.loads(result.value.bytes_.decode())
                await self._handle(msg.get("event", {}))
        except asyncio.CancelledError:
            pass
        except StopAsyncIteration:
            self.closed_reason = "stream ended"
        except Exception as e:
            self.closed_reason = str(e)
            log.warning("sonic read error: %s", e)
            await self.on_event({"type": "error", "message": f"voice model stream error: {e}"[:300]})
        finally:
            was = self.active
            self.active = False
            if was:
                await self.on_event({"type": "model_closed", "reason": self.closed_reason or "closed"})

    async def _handle(self, ev: dict[str, Any]) -> None:
        if "contentStart" in ev:
            cs = ev["contentStart"]
            cid = cs.get("contentId", "")
            self._role[cid] = cs.get("role", "")
            stage = ""
            if cs.get("additionalModelFields"):
                try:
                    stage = json.loads(cs["additionalModelFields"]).get("generationStage", "")
                except (ValueError, AttributeError):
                    pass
            self._stage[cid] = stage
            if cs.get("role") == "USER" and cs.get("type") == "TEXT":
                self._spoken = []
        elif "textOutput" in ev:
            t = ev["textOutput"]
            text, role = t.get("content", ""), t.get("role", "")
            cid = t.get("contentId", "")
            if '"interrupted"' in text and "true" in text:
                await self.on_event({"type": "interrupted"})
                return
            if role == "USER":
                await self.on_event({"type": "transcript", "role": "user", "text": text})
            elif role == "ASSISTANT":
                stage = self._stage.get(cid, "")
                if stage == "SPECULATIVE":
                    self._spoken.append(text.strip())
                    await self.on_event({"type": "transcript", "role": "assistant", "text": text})
                elif text.strip() not in self._spoken:
                    await self.on_event({"type": "transcript", "role": "assistant", "text": text, "stage": "final"})
        elif "audioOutput" in ev:
            await self.on_audio(base64.b64decode(ev["audioOutput"]["content"]))
        elif "toolUse" in ev:
            self._tool_use = ev["toolUse"]
        elif "contentEnd" in ev:
            ce = ev["contentEnd"]
            if ce.get("type") == "TOOL" and self._tool_use:
                tu, self._tool_use = self._tool_use, None
                task = asyncio.create_task(self._run_tool(tu))
                self._tool_tasks.add(task)
                task.add_done_callback(self._tool_tasks.discard)
            elif ce.get("stopReason") == "INTERRUPTED":
                await self.on_event({"type": "interrupted"})
        elif "completionEnd" in ev:
            pass
        elif "usageEvent" in ev:
            pass

    async def _run_tool(self, tu: dict) -> None:
        name = tu.get("toolName", "")
        try:
            args = json.loads(tu.get("content") or "{}")
        except ValueError:
            args = {}
        result = await self.on_tool(name, args if isinstance(args, dict) else {})
        cname = str(uuid.uuid4())
        p = self.prompt
        await self._send({"contentStart": {"promptName": p, "contentName": cname, "interactive": False,
                                           "type": "TOOL", "role": "TOOL",
                                           "toolResultInputConfiguration": {
                                               "toolUseId": tu.get("toolUseId", ""), "type": "TEXT",
                                               "textInputConfiguration": {"mediaType": "text/plain"}}}})
        await self._send({"toolResult": {"promptName": p, "contentName": cname,
                                         "content": json.dumps(result, ensure_ascii=False)}})
        await self._send({"contentEnd": {"promptName": p, "contentName": cname}})
