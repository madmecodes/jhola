"""A deterministic, scripted Strands model provider.

It plays the part of the LLM: a scenario script is a generator that yields the tool
calls (or final text) a real model would emit, and receives the real tool results back.
The Strands agent loop, the tools, Cedar, the mandate service and the audit log all run
for real; only the language model is replaced.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, Generator

from strands.models.model import Model


@dataclass
class Call:
    name: str
    input: dict


@dataclass
class Say:
    text: str


Step = list[Call] | Call | Say
Script = Callable[[], Generator[Step, list[Any], None]]

_ids = itertools.count(1)


class ScriptedModel(Model):
    def __init__(self, script: Script, name: str = "scripted-stub") -> None:
        self.script = script
        self.config = {"model_id": name}
        self._gen: Generator | None = None
        self._pending_ids: list[str] = []
        self.transcript: list[Step] = []

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> Any:
        return self.config

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs) -> AsyncGenerator:
        raise NotImplementedError("scripted model does not support structured output")
        yield  # pragma: no cover

    def _tool_results(self, messages) -> list[Any]:
        by_id = {}
        if messages and messages[-1]["role"] == "user":
            for block in messages[-1]["content"]:
                tr = block.get("toolResult")
                if tr:
                    text = "".join(c.get("text", "") for c in tr.get("content", []))
                    try:
                        by_id[tr["toolUseId"]] = json.loads(text)
                    except (json.JSONDecodeError, TypeError):
                        by_id[tr["toolUseId"]] = text
        return [by_id.get(i) for i in self._pending_ids]

    def _next_step(self, messages) -> Step:
        if self._gen is None:
            self._gen = self.script()
            return next(self._gen)
        return self._gen.send(self._tool_results(messages))

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs) -> AsyncGenerator:
        try:
            step = self._next_step(messages)
        except StopIteration:
            step = Say("OK.")
        self.transcript.append(step)
        yield {"messageStart": {"role": "assistant"}}
        if isinstance(step, Say):
            yield {"contentBlockDelta": {"delta": {"text": step.text}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        else:
            calls = step if isinstance(step, list) else [step]
            self._pending_ids = []
            for c in calls:
                tid = f"tooluse_stub_{next(_ids)}"
                self._pending_ids.append(tid)
                yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": tid, "name": c.name}}}}
                yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(c.input)}}}}
                yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        yield {"metadata": {"usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                            "metrics": {"latencyMs": 0}}}
