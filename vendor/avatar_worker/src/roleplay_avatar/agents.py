"""Provider-neutral streaming and bounded structured agents."""

import json
import os

import httpx

from .models import agent_config, prompt_text


async def sse_events(lines):
    """Decode SSE data blocks, including multiline JSON and comments."""
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


class ModelGateway:
    def __init__(self, role="roleplay", url=None, *, config=None, transport=None):
        self.role = role
        self.config = dict(config if config is not None else agent_config(role))
        self.transport = transport
        if url:
            self.config["url"] = url

    def request(self, system, messages, max_tokens, temperature):
        config = self.config
        backend = config["backend"]
        key = os.environ.get(config.get("api_key_env", "AVATAR_LLM_API_KEY"), "")
        if backend != "local" and config.get("require_key", False) and not key:
            raise ValueError(f"Set {config.get('api_key_env', 'AVATAR_LLM_API_KEY')} for {self.role}")
        generation = {"max_tokens": max_tokens, "temperature": temperature, **config.get("generation", {})}
        headers = {"Authorization": "Bearer " + key} if key else {}
        if backend == "local":
            route = "/chat"
            payload = {**generation, "persona": system, "messages": messages}
        elif backend == "anthropic":
            converted = []
            for message in messages:
                content = message["content"]
                if isinstance(content, list):
                    blocks = []
                    for block in content:
                        if block.get("type") == "image_url":
                            image = block["image_url"]["url"]
                            if image.startswith("data:"):
                                mime, data = image[5:].split(";base64,", 1)
                                blocks.append(
                                    {
                                        "type": "image",
                                        "source": {"type": "base64", "media_type": mime, "data": data},
                                    }
                                )
                            else:
                                blocks.append({"type": "image", "source": {"type": "url", "url": image}})
                        else:
                            blocks.append(block)
                    content = blocks
                converted.append({**message, "content": content})
            messages = converted
            route = "/messages"
            headers = {"anthropic-version": "2023-06-01", **({"x-api-key": key} if key else {})}
            payload = {
                **generation,
                "model": config["model"],
                "system": system,
                "messages": messages,
                "stream": True,
            }
        elif backend == "openai-responses":
            route = "/responses"
            generation["max_output_tokens"] = generation.pop("max_tokens")
            converted = []
            for message in messages:
                content = message["content"]
                if isinstance(content, list):
                    blocks = []
                    for block in content:
                        if block.get("type") == "text":
                            blocks.append({"type": "input_text", "text": block["text"]})
                        elif block.get("type") == "image_url":
                            image = block["image_url"]
                            blocks.append({"type": "input_image", "image_url": image["url"],
                                           **({"detail": image["detail"]} if "detail" in image else {})})
                        else:
                            blocks.append(block)
                    content = blocks
                converted.append({**message, "content": content})
            payload = {
                **generation,
                "model": config["model"],
                "instructions": system,
                "input": converted,
                "stream": True,
            }
        elif backend == "openai":
            route = "/chat/completions"
            if config.get("max_tokens_field") == "max_completion_tokens":
                generation["max_completion_tokens"] = generation.pop("max_tokens")
            payload = {
                **generation,
                "model": config["model"],
                "messages": [{"role": "system", "content": system}, *messages],
                "stream": True,
            }
        else:
            raise ValueError(f"Unsupported protocol: {backend}")
        # Provider extensions (thinking/reasoning/etc.) are explicit. Routing stays fixed.
        extra = config.get("extra_body", {})
        if set(extra) & {"model", "messages", "system", "input", "instructions", "stream", "persona"}:
            raise ValueError("extra_body cannot override message or routing fields")
        payload.update(extra)
        payload = {k: v for k, v in payload.items() if v is not None}
        return config["url"].rstrip("/") + route, headers, payload

    async def stream(self, system, messages, *, max_tokens=1024, temperature=0.7):
        url, headers, payload = self.request(system, messages, max_tokens, temperature)
        backend = self.config["backend"]
        timeout = httpx.Timeout(self.config.get("timeout_s", 180), connect=10)
        async with (
            httpx.AsyncClient(
                trust_env=False, timeout=timeout, **({"transport": self.transport} if self.transport else {})
            ) as client,
            client.stream("POST", url, json=payload, headers=headers) as response,
        ):
            response.raise_for_status()
            lines = response.aiter_lines()
            events = lines if backend == "local" else sse_events(lines)
            async for data in events:
                if not data or data == "[DONE]":
                    continue
                item = json.loads(data)
                kind = item.get("type")
                if "error" in item or kind in {"error", "response.failed", "response.incomplete"}:
                    raise RuntimeError(f"Model provider failed for {self.role}")
                if backend == "local":
                    text = item.get("text", "")
                elif backend == "anthropic":
                    delta = item.get("delta", {})
                    text = delta.get("text", "") if kind == "content_block_delta" else ""
                elif backend == "openai-responses":
                    text = item.get("delta", "") if kind == "response.output_text.delta" else ""
                else:
                    text = (item.get("choices") or [{}])[0].get("delta", {}).get("content") or ""
                if isinstance(text, str) and text:
                    yield text

    async def structured(self, system, data, schema, *, max_tokens=700):
        system = prompt_text(self.role, system)
        prompt = (
            system
            + "\nReturn one complete JSON object matching this JSON schema:\n"
            + json.dumps(schema.model_json_schema(), ensure_ascii=False)
        )
        raw = ""
        async for token in self.stream(
            prompt,
            [{"role": "user", "content": json.dumps(data, ensure_ascii=False)}],
            max_tokens=max_tokens,
            temperature=0.4,
        ):
            raw += token
            if len(raw) > 24000:
                raise ValueError("Agent output exceeded its limit")
        start = raw.find("{")
        if start < 0:
            raise ValueError("Agent did not return JSON")
        value, _ = json.JSONDecoder().raw_decode(raw[start:])
        return schema.model_validate(value)


AGENT_ROLES = {
    "roleplay": {"purpose": "Character dialogue", "output": "Segment or actor text"},
    "performance_director": {
        "purpose": "Convert actor text to playable speech, emotion and actions",
        "output": "Segment",
    },
    "initiative": {"purpose": "Decide when and why to initiate conversation", "output": "InitiativeDecision"},
    "character_design": {"purpose": "Expand character and voice briefs", "output": "CharacterDesign"},
    "voice_direction": {"purpose": "Choose speech delivery", "output": "Delivery"},
    "vision": {"purpose": "Image-grounded character design", "output": "Character plan"},
}
