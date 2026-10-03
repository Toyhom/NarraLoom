"""OpenAI-compatible model gateway; cancellable SSE and strict bounded JSON.

SSE framing adapted from Roleplay Avatar agents.py (MIT), source 4e69b83.
See NOTICE.md and licenses/roleplay-avatar-MIT.txt.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import httpx
from pydantic import ValidationError

from .config import default_workspace
from .contracts import DomainError
from .decisions import DecisionRequest, validate_response
from .embeddings import validate_embeddings
from .engines import builtin_engines, sse_events

__all__ = ["ModelGateway", "sse_events"]
from .settings import MODEL_OWNER


class ModelGateway:
    def __init__(self, config, trace_root: Path, settings=None, registry=None, *, secrets_root=None):
        self.registry = registry or builtin_engines()
        self.settings = settings
        self.config = config
        self.secrets_root = Path(secrets_root or default_workspace() / "secrets").resolve()
        self.trace_root = trace_root
        self.trace_root.mkdir(parents=True, exist_ok=True)
        from .semantic_memory import SemanticMemory
        self.memory = SemanticMemory(self)

    def effective_config(self):
        return self.settings.effective(MODEL_OWNER.get()) if self.settings else self.config

    def role_config(self, role):
        config = self.effective_config()
        binding = config.get("bindings", {}).get(role)
        overrides = config.get("roles", {}).get(role, {})
        if binding:
            provider = config.get("providers", {}).get(binding["provider"])
            if provider is None:
                raise DomainError("model_config", "模块引用的服务商不存在", 503)
            # A named endpoint receives only its own credentials and options.
            return {**{k: overrides[k] for k in ("max_tokens", "output_chars") if k in overrides},
                    **provider, **binding, "api_key_env": provider.get("api_key_env", "RPW_NO_INHERITED_KEY")}
        default = config.get("default", {})
        if role in {"action_router", "memory_embedding"}:
            return {}  # Auxiliary modules use an explicit provider binding.
        merged = {**default, **overrides}
        if overrides.get("url", "").rstrip("/") and overrides["url"].rstrip("/") != default.get("url", "").rstrip("/"):
            for key in ("api_key", "api_key_file", "api_key_env"):
                merged.pop(key, None)
                if key in overrides:
                    merged[key] = overrides[key]
            merged.setdefault("api_key_env", "RPW_NO_INHERITED_KEY")
        return merged

    def record_trace(self, action_id, budget, trace):
        (self.trace_root / f'{action_id}-{time.time_ns()}-{budget["calls"]}-{trace["role"]}.json').write_text(
            json.dumps(trace, ensure_ascii=False, indent=2))
        if self.settings:
            try:
                self.settings.record_usage(MODEL_OWNER.get(), trace)
            except OSError:
                logging.getLogger(__name__).exception("Usage ledger write failed")
        public = {k: v for k, v in trace.items() if k in {
            "role", "model", "response_model", "call", "duration_s", "usage", "provider",
            "backend", "revision", "status", "error", "routing"}}
        budget["traces"].append(public)
        return public

    def configured(self, role):
        config = self.role_config(role)
        backend = config.get("backend", "systemone" if role == "action_router" else "openai")
        return bool(config.get("model") and (config.get("url") or backend not in {"openai", "systemone", "openai_embedding"}))

    async def embed(self, role, texts, action_id, budget, *, configuration=None):
        config = self.role_config(role) if configuration is None else configuration
        if not config.get('model'):
            raise DomainError('embedding_unconfigured', 'Configure an embedding provider for this module', 503)
        engine = self.registry.require(config.get('backend', 'openai_embedding'), 'embed')
        if (not isinstance(texts, list) or not 1 <= len(texts) <= 128
                or any(not isinstance(text, str) or not text or len(text) > 16000 for text in texts)):
            raise DomainError('embedding_input', 'Embedding input requires 1–128 bounded nonempty texts', 422)
        payload = {'model': config['model'], 'input': texts, 'encoding_format': 'float'}
        if len(json.dumps(payload, ensure_ascii=False)) > config.get('context_chars', 120000):
            raise DomainError('context_limit', 'Embedding input exceeds the provider context budget', 422)
        if budget['calls'] >= budget.get('max_calls', 12):
            raise DomainError('embedding_budget', 'Embedding call budget exhausted', 502)
        budget['calls'] += 1
        trace = {'role': role, 'model': config['model'], 'response_model': None,
                 'provider': config.get('provider', 'default'), 'backend': engine.name,
                 'revision': config.get('revision', ''), 'call': budget['calls'],
                 'usage': None, 'context': {'input': texts}, 'status': 'failed'}
        started = time.monotonic()
        try:
            async with asyncio.timeout(config.get('timeout_s', 30)):
                raw = await engine.invoke(config, payload, self.auth_headers(config))
            result = validate_embeddings(raw, len(texts))
            trace.update(status='ok', response_model=result['model'], usage=result['usage'],
                         dimensions=len(result['vectors'][0]), input_count=len(texts))
            return result
        except asyncio.CancelledError:
            trace['status'] = 'cancelled'
            raise
        except (httpx.HTTPError, TimeoutError) as exc:
            trace['error'] = 'embedding_unavailable'
            raise DomainError('embedding_unavailable', 'Embedding service is unavailable', 503) from exc
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            trace.update(status='invalid_output', error='invalid_embedding_output')
            raise DomainError('invalid_embedding_output', 'Embedding service returned invalid vectors', 502) from exc
        finally:
            trace['duration_s'] = round(time.monotonic() - started, 4)
            self.record_trace(action_id, budget, trace)

    async def decide(self, role, request: DecisionRequest, action_id, budget):
        config = self.role_config(role)
        if not self.configured(role):
            raise DomainError("decision_unconfigured", "请先为决策模块绑定服务商和模型", 503)
        engine = self.registry.require(config.get("backend", "systemone"), "decide")
        payload = {"model": config["model"], **request.model_dump(exclude_none=True)}
        if len(json.dumps(payload, ensure_ascii=False)) > config.get("context_chars", 120000):
            raise DomainError("context_limit", "决策输入超过此服务的上下文预算", 422)
        if budget["calls"] >= budget.get("max_calls", 6):
            raise DomainError("model_budget", "本轮模型调用达到上限", 502)
        budget["calls"] += 1
        started = time.monotonic()
        trace = {"role": role, "model": config["model"], "response_model": None,
                 "provider": config.get("provider", "default"), "backend": engine.name,
                 "revision": config.get("revision", ""), "call": budget["calls"],
                 "usage": None, "context": payload, "status": "failed"}
        try:
            async with asyncio.timeout(config.get("timeout_s", 15)):
                raw = await engine.invoke(config, payload, self.auth_headers(config))
            trace["output"] = raw
            result = validate_response(request, raw)
            trace.update(status="ok", response_model=result["model"], usage=result["usage"], output=result["answers"])
            return result
        except (httpx.HTTPError, TimeoutError) as exc:
            trace["error"] = "decision_unavailable"
            raise DomainError("decision_unavailable", "决策服务连接失败", 503) from exc
        except (ValueError, TypeError, KeyError) as exc:
            trace["error"] = "invalid_decision_output"
            raise DomainError("invalid_decision_output", "决策服务返回了无效的类型或概率分布", 502) from exc
        finally:
            trace["duration_s"] = round(time.monotonic() - started, 4)
            self.record_trace(action_id, budget, trace)

    def auth_headers(self, config):
        key = config.get("api_key") or os.environ.get(config.get("api_key_env", "RPW_API_KEY"), "")
        if not key and config.get("api_key_file"):
            supplied = Path(config["api_key_file"])
            # Legacy configs use secrets/name; new configs can use name relative
            # to the explicitly configured secrets root, or an absolute file.
            if not supplied.is_absolute() and supplied.parts and supplied.parts[0] == "secrets":
                supplied = Path(*supplied.parts[1:])
            path = (self.secrets_root / supplied).resolve()
            if not path.is_relative_to(self.secrets_root):
                raise DomainError("model_config", "API 密钥文件必须位于配置的 secrets_root 目录", 503)
            try:
                key = path.read_text().strip()
            except OSError as exc:
                raise DomainError("model_config", "无法读取模型密钥文件", 503) from exc
        return {"Authorization": "Bearer " + key} if key else {}

    async def health(self):
        config = self.role_config("game_master")
        if not self.configured("game_master"):
            return {"ready": False, "message": "尚未配置模型服务"}
        try:
            engine = self.registry.require(config.get("backend", "openai"), "generate")
            if engine.probe is None:
                return {"ready": None, "configured": True, "backend": engine.name,
                        "mode": "unprobed", "message": "此后端未提供健康探测；请运行模块连接测试"}
            async with asyncio.timeout(4):
                return await engine.probe(config, self.auth_headers(config))
        except (httpx.HTTPError, TimeoutError, KeyError, ValueError, DomainError):
            return {"ready": False, "message": "模型服务暂时不可用，请检查连接"}

    async def generate(self, role, system, data, schema, action_id, budget, validate=None):
        config = self.role_config(role)
        if not self.configured(role):
            raise DomainError("model_unconfigured", "请先配置模型服务", 503)
        engine = self.registry.require(config.get("backend", "openai"), "generate")
        raw, validation_error = "", ""
        max_repairs = budget.get("max_repairs", 1)
        for attempt in range(max_repairs + 1):
            if budget["calls"] >= budget.get("max_calls", 5) or (attempt and budget["repairs"] >= max_repairs):
                raise DomainError("model_budget", "本轮模型调用达到上限，请重试这一行动", 502)
            if attempt:
                budget["repairs"] += 1
            budget["calls"] += 1
            payload = {
                "model": config["model"], "stream": True, "stream_options": {"include_usage": True},
                "temperature": 0 if role == "content_reviewer" else 0.3 if role == "game_master" else 0.65,
                "max_tokens": config.get("max_tokens", {
                    "world_builder": 2800, "story_builder": 3000, "rules_builder": 6000,
                    "simulation_builder": 4000, "world_actor": 1000, "import_builder": 10000, "state_builder": 6000,
                    "content_reviewer": 1800,
                    "game_master": 900}.get(role, 700)),
                "messages": [
                    {"role": "system", "content": system + "\n只返回一个合法 JSON 对象，必须遵守此 Schema：\n"
                     + json.dumps(schema.model_json_schema(), ensure_ascii=False)},
                    {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
                ],
                **config.get("extra_body", {}),
            }
            if config.get("json_schema", False):
                payload["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": schema.__name__, "schema": schema.model_json_schema()}}
            elif config.get("json_object", False):
                payload["response_format"] = {"type": "json_object"}
            if attempt:
                payload["messages"].append({"role": "assistant", "content": raw[:10000]})
                payload["messages"].append({"role": "user", "content":
                    "上次输出不符合 Schema。请依据具体错误修复，不得重复非法枚举。保持原语义，只输出 JSON。错误："
                    + validation_error})
            if len(json.dumps(payload, ensure_ascii=False)) > config.get(
                "context_chars", 40000 if role.endswith("builder") else 30000
            ):
                raise DomainError("context_limit", "当前场景内容超过模型上下文预算", 422)
            started, raw, usage = time.monotonic(), "", None
            headers = self.auth_headers(config)
            trace = {"role": role, "model": config["model"], "response_model": None, "call": budget["calls"],
                     "provider": config.get("provider", "default"), "backend": engine.name,
                     "revision": config.get("revision", ""), "status": "failed", "usage": None, "context": data,
                     "system_prompt": system, "output_schema": schema.model_json_schema()}
            transport_finished = False
            try:
                async with asyncio.timeout(config.get("timeout_s", 90)):
                    response = await engine.invoke(config, payload, headers)
                raw, usage = response["text"], response.get("usage")
                if not isinstance(raw, str) or len(raw) > config.get("output_chars", 22000):
                    raise DomainError("model_output_limit", "模型输出超过此模块的预算", 502)
                trace.update(response_model=response["model"], usage=usage, output=raw, status="ok")
                transport_finished = True
            except (httpx.HTTPError, TimeoutError) as e:
                trace["error"] = "model_unavailable"
                raise DomainError("model_unavailable", "模型连接中断；世界没有改变，可以重试", 503) from e
            finally:
                trace["duration_s"] = round(time.monotonic() - started, 3)
                if not transport_finished:
                    self.record_trace(action_id, budget, trace)
            try:
                text = raw.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                result = schema.model_validate(json.loads(text))
                if validate:
                    validate(result)
                return result
            except (ValueError, ValidationError, DomainError) as exc:
                trace["status"] = "invalid_output"
                validation_error = (json.dumps(exc.errors(include_url=False, include_input=False, include_context=False), ensure_ascii=False)
                                    if isinstance(exc, ValidationError) else str(exc))
                if attempt == max_repairs:
                    detail = exc.message if isinstance(exc, DomainError) else "模型未按约定给出完整内容"
                    raise DomainError("invalid_model_output", detail + "；本轮未提交，可以重试", 502)
            finally:
                self.record_trace(action_id, budget, trace)
        raise AssertionError("Unreachable")
