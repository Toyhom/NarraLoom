"""Small transport registry. Optional engines require no changes to world rules.

SSE framing adapted from Roleplay Avatar agents.py (MIT), source 4e69b83.
See NOTICE.md and licenses/roleplay-avatar-MIT.txt.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from .contracts import DomainError


async def sse_events(lines):
    data = []
    async for line in lines:
        if not line:
            if data:
                yield "\n".join(data)
                data = []
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        yield "\n".join(data)


@dataclass(frozen=True)
class Engine:
    name: str
    capabilities: frozenset[str]
    invoke: Callable[[dict, dict, dict], Awaitable[dict]]
    probe: Callable[[dict, dict], Awaitable[dict]] | None = None


class EngineRegistry:
    def __init__(self):
        self.engines = {}

    def register(self, engine: Engine):
        if engine.name in self.engines or not engine.capabilities or engine.capabilities - {"generate", "decide"}:
            raise ValueError("duplicate engine or invalid capabilities")
        self.engines[engine.name] = engine

    def require(self, name, capability):
        engine = self.engines.get(name)
        if not engine or capability not in engine.capabilities:
            raise DomainError("engine_capability", "模型后端不支持此模块的任务类型", 422)
        return engine

    def describe(self):
        return [{"id": e.name, "capabilities": sorted(e.capabilities)} for e in self.engines.values()]


async def openai_generate(config, payload, headers):
    raw, usage, response_model = "", None, config["model"]
    async with (
        httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(config.get("timeout_s", 90), connect=5)) as client,
        client.stream("POST", config["url"].rstrip("/") + "/chat/completions",
                      json=payload, headers=headers) as response,
    ):
        response.raise_for_status()
        async for part in sse_events(response.aiter_lines()):
            if part == "[DONE]":
                break
            item = json.loads(part)
            response_model = item.get("model") or response_model
            if "error" in item:
                raise DomainError("model_error", "模型服务未能完成回复", 502)
            if item.get("usage"):
                usage = item["usage"]
            for choice in item.get("choices", []):
                raw += choice.get("delta", {}).get("content") or ""
            if len(raw) > config.get("output_chars", 22000):
                raise DomainError("model_output_limit", "模型输出过长", 502)
    return {"text": raw, "model": response_model, "usage": usage}


async def systemone_decide(config, payload, headers):
    # url includes /v1, exactly like the OpenAI provider base URL. No redirects.
    async with (
        httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(config.get("timeout_s", 15), connect=5)) as client,
        client.stream("POST", config["url"].rstrip("/") + "/systemone", json=payload, headers=headers) as response,
    ):
        response.raise_for_status()
        content = bytearray()
        async for chunk in response.aiter_bytes():
            content.extend(chunk)
            if len(content) > 262144:
                raise DomainError("decision_output_limit", "决策服务返回内容过大", 502)
    return json.loads(content)


def builtin_engines():
    registry = EngineRegistry()
    registry.register(Engine("openai", frozenset({"generate"}), openai_generate, openai_probe))
    registry.register(Engine("systemone", frozenset({"decide"}), systemone_decide))
    return registry


async def openai_probe(config, headers):
    async with httpx.AsyncClient(trust_env=False, timeout=4) as client:
        response = await client.get(config["url"].rstrip("/") + "/models", headers=headers)
    response.raise_for_status()
    available = {m["id"] for m in response.json().get("data", [])}
    if available and config["model"] not in available:
        return {"ready": False, "message": "配置的模型不在服务模型列表中"}
    return {"ready": True, "model": config["model"], "mode": "live"}
