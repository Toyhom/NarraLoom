"""Embeddable, single-writer API. Ownership and story visibility are independent."""

import asyncio
import hashlib
import json
import re
import secrets
import time
from contextlib import AsyncExitStack, asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .avatars import MAX_AVATAR_UPLOAD, AvatarCreate, AvatarService
from .backups import MAX_BACKUP, export_campaign, preview_backup, restore_campaign
from .catalog import get_pack, install, load_catalog, public_pack
from .config import AppConfig
from .content import (
    CreateStory,
    CreateWorld,
    EditStory,
    EditWorld,
    RepairStory,
    StoryBlueprint,
    WorldBlueprint,
    compile_story,
    validate_story,
    validate_world,
)
from .continuity import carry_world
from .contracts import ActionCommand, DomainError, ForkRequest, Identifier, NewCampaign
from .decisions import DecisionQuestion, DecisionRequest
from .gateway import ModelGateway
from .idempotency import identity, receipt
from .imports import MAX_UPLOAD, ConvertRequest, preview, receive, submit_conversion
from .journal import digest
from .memory import retrieve
from .packages import (
    MAX_PACKAGE,
    PackageBuild,
    PackageInstall,
    PackageVisibility,
    build_package,
    install_package,
    package_path,
    preview_package,
    public_package,
    read_package,
    set_visibility,
    visible_package,
)
from .rooms import RoomAction, RoomControl, RoomCreate, RoomJoin, Rooms
from .runtime import Runtime
from .semantic_memory import RecallRequest
from .settings import (
    DECISION_ROLES,
    EMBEDDING_ROLES,
    MODEL_OWNER,
    ROLES,
    ProviderSettings,
    Settings,
    capability,
    require_idle,
)
from .store import Store, public_action, public_history
from .studio import Studio, public_content
from .world import project


def create_app(data_root=None, gateway=None, *, config: AppConfig | None = None, model_config=None,
               registry=None, avatar_factory=None, check_registry=None, action_registry=None):
    """Create an ASGI app. Explicit config does not inherit RPW environment paths.

    registry extends the normal gateway; gateway replaces it entirely. Optional
    avatar_factory(store) supplies a host-owned presentation adapter.
    """
    if gateway is not None and registry is not None:
        raise ValueError("Pass registry for the built-in gateway, or an injected gateway, not both")
    config = config if config is not None else AppConfig.from_env()
    if data_root is not None:
        config = replace(config, data_root=data_root)
    model_config = config.load_models() if model_config is None else deepcopy(model_config)
    if not isinstance(model_config, dict):
        raise TypeError("Model configuration must be a mapping")
    template = json.loads((Path(__file__).parent / "builtin/fogharbor.json").read_text())
    catalog = load_catalog()

    @asynccontextmanager
    async def lifespan(app):
        async with AsyncExitStack() as resources:
            store = Store(config.data_root, check_registry=check_registry, action_registry=action_registry)
            resources.callback(store.close)
            settings = Settings(config.data_root / "provider-settings", model_config)
            model = gateway if gateway is not None else ModelGateway(
                model_config, config.output_root / "model-traces", settings,
                registry=registry, secrets_root=config.secrets_root)
            app.state.settings = settings
            app.state.store = store
            app.state.runtime = Runtime(store, model)
            resources.push_async_callback(app.state.runtime.close)
            app.state.gateway = model
            app.state.studio = Studio(store, model, config.output_root / "content-tests")
            resources.push_async_callback(app.state.studio.close)
            app.state.avatars = (avatar_factory(store) if avatar_factory is not None else
                                 AvatarService(store, workspace_root=config.workspace_root))
            app.state.rooms = Rooms(store)
            yield

    app = FastAPI(title="NarraLoom", version=__version__, lifespan=lifespan)
    app.state.config = config

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Pydantic may include a complete request body in model-level errors.
        # Return useful field locations/messages without echoing keys or images.
        return JSONResponse({"detail": [{k: e[k] for k in ("type", "loc", "msg") if k in e}
                                        for e in exc.errors()]}, status_code=422)

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            try:
                size = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"message": "无效的请求长度"}, status_code=400)
            limit = MAX_PACKAGE if request.url.path in {"/api/studio/packages/import", "/api/studio/packages/preview"} else MAX_BACKUP if request.url.path.startswith("/api/backups") else MAX_AVATAR_UPLOAD if request.url.path == "/api/avatars" else MAX_UPLOAD if request.url.path == "/api/studio/imports" else (
                512000 if request.url.path.startswith(("/api/studio", "/api/decisions/")) else 24000)
            if size > limit:
                return JSONResponse({"message": "请求内容过大"}, status_code=413)
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                return JSONResponse({"message": "不允许跨站修改"}, status_code=403)
            if request.url.path != "/api/session":
                session = request.cookies.get("rpw_session", "")
                expected = hashlib.sha256(("csrf:" + session).encode()).hexdigest()
                if not session or not secrets.compare_digest(request.headers.get("x-csrf-token", ""), expected):
                    return JSONResponse({"message": "会话已过期，请刷新页面"}, status_code=403)
        sid = request.cookies.get("rpw_session", "")
        token = MODEL_OWNER.set(hashlib.sha256(sid.encode()).hexdigest() if re.fullmatch(r"[a-f0-9]{64}", sid) else None)
        try:
            response = await call_next(request)
        finally:
            MODEL_OWNER.reset(token)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def owner(request):
        session = request.cookies.get("rpw_session", "")
        if not re.fullmatch(r"[a-f0-9]{64}", session):
            raise DomainError("session_required", "请先建立浏览器会话", 401)
        return hashlib.sha256(session.encode()).hexdigest()

    @app.post("/api/session")
    async def session(request: Request):
        sid = request.cookies.get("rpw_session", "")
        if not re.fullmatch(r"[a-f0-9]{64}", sid):
            sid = secrets.token_hex(32)
        response = JSONResponse({"csrf_token": hashlib.sha256(("csrf:" + sid).encode()).hexdigest()})
        response.set_cookie("rpw_session", sid, httponly=True, samesite="strict", max_age=31536000,
                            secure=request.url.scheme == "https")
        return response

    @app.get("/healthz")
    async def health():
        if app.state.store.journal.poisoned:
            return JSONResponse({"status": "recovery_required", "storage": "single-writer-journal"}, status_code=503)
        return {"status": "ok", "version": app.version, "storage": "single-writer-journal"}

    @app.get("/api/status")
    async def status():
        return await app.state.gateway.health()

    @app.get("/api/settings/provider")
    async def provider(request: Request):
        return app.state.settings.public(owner(request))

    @app.put("/api/settings/provider")
    async def save_provider(request: Request, payload: ProviderSettings):
        user = owner(request); require_idle(app.state.store, user)
        for role, binding in payload.bindings.items():
            app.state.gateway.registry.require(payload.providers[binding.provider].backend,
                                               capability(role))
        return app.state.settings.save(user, payload)

    @app.delete("/api/settings/provider")
    async def reset_provider(request: Request):
        user = owner(request); require_idle(app.state.store, user)
        return app.state.settings.reset(user)

    @app.post("/api/settings/provider/check")
    async def check_provider(request: Request):
        user = owner(request)
        effective = app.state.settings.effective(user)
        gateway = ModelGateway(effective, config.output_root / "model-traces", app.state.settings,
                               registry=app.state.gateway.registry, secrets_root=config.secrets_root)
        health = await gateway.health()
        if health.get("ready") is False:
            return {**health, "generation_passed": False}
        from .contracts import ActorReply
        budget = {"calls": 0, "repairs": 0, "traces": [], "max_calls": 1, "max_repairs": 0}
        reply = await gateway.generate("character_actor", "这是连接诊断。用一个简短中文问候填写text，其余字段取默认值。", {},
                                       ActorReply, "diagnostic_" + secrets.token_hex(10), budget)
        return {**health, "ready": True, "generation_passed": True, "sample": reply.text, "traces": budget["traces"]}

    @app.get("/api/settings/usage")
    async def usage(request: Request):
        return app.state.settings.report(owner(request))

    @app.get("/api/actions/{aid}/diagnostics")
    async def action_diagnostics(aid: str, request: Request):
        action = app.state.store.action(aid, owner(request))
        return {"action_id": aid, "status": action["status"], "traces": action.get("traces", [])}

    @app.get("/api/engines")
    async def engines(request: Request):
        owner(request)
        gateway = app.state.gateway
        modules = []
        for role in (*ROLES, *DECISION_ROLES, *EMBEDDING_ROLES):
            config = gateway.role_config(role)
            modules.append({"id": role, "capability": capability(role),
                            **{k: config.get(k) for k in ("model", "revision")},
                            "provider": config.get("provider", "default"),
                            "backend": config.get("backend", "openai_embedding" if role in EMBEDDING_ROLES else "systemone" if role in DECISION_ROLES else "openai"),
                            "configured": gateway.configured(role)})
        return {"schema_version": "1.0", "engines": gateway.registry.describe(), "modules": modules,
                "decision_policy": gateway.effective_config().get("decision_policy", {"mode": "off"}),
                "memory_policy": gateway.effective_config().get('memory_policy', {'mode': 'lexical'})}

    @app.post("/api/engines/{role}/check")
    async def check_engine(role: str, request: Request):
        owner(request)
        gateway = app.state.gateway
        budget = {"calls": 0, "repairs": 0, "traces": [], "max_calls": 1, "max_repairs": 0}
        diagnostic_id = "engine_check_" + secrets.token_hex(10)
        if role in EMBEDDING_ROLES:
            result = await gateway.embed(role, ['The visitor returned the borrowed instrument.',
                                               '客人归还了借来的乐器。'], diagnostic_id, budget)
            return {'protocol_passed': True, 'sample': {'model': result['model'],
                    'dimensions': len(result['vectors'][0]), 'inputs': len(result['vectors'])}, 'traces': budget['traces']}
        if role in DECISION_ROLES:
            result = await gateway.decide(role, DecisionRequest(state="The door is closed.", questions={
                "closed": DecisionQuestion(type="noul", instructions="Is the door closed?")}), diagnostic_id, budget)
            return {"protocol_passed": True, "answers": result["answers"], "traces": budget["traces"]}
        if role not in ROLES:
            raise DomainError("unknown_module", "未知引擎模块", 404)
        from .contracts import ActorReply
        result = await gateway.generate(role, "Connection test. Put a short greeting in text; use defaults otherwise.",
                                        {}, ActorReply, diagnostic_id, budget)
        return {"protocol_passed": True, "sample": result.text, "traces": budget["traces"]}

    @app.post("/api/decisions/{role}")
    async def decision(role: str, payload: DecisionRequest, request: Request):
        owner(request)
        if role not in DECISION_ROLES:
            raise DomainError("unknown_module", "未知决策模块", 404)
        budget = {"calls": 0, "traces": [], "max_calls": 1}
        result = await app.state.gateway.decide(role, payload, "decision_" + secrets.token_hex(10), budget)
        return {**result, "traces": budget["traces"]}

    @app.get("/api/worlds")
    async def worlds():
        return [{"id": template["id"], "title": template["title"], "premise": template["premise"],
                 "opening": template["opening"], "locations": len(template["locations"]),
                 "characters": len(template["actors"]) - 1}]

    @app.get("/api/avatars/capabilities")
    async def avatar_capabilities():
        return {"available": app.state.avatars.enabled, "mode": "generated_webgl_2d", "max_image_mb": 10}

    @app.get("/api/avatars")
    async def avatar_library(request: Request):
        user=owner(request)
        return [await app.state.avatars.status(a["id"],user)
                for a in list(app.state.store.avatars.values()) if a["owner"]==user]

    @app.post("/api/avatars", status_code=202)
    async def create_avatar(request: Request):
        user=owner(request);body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>MAX_AVATAR_UPLOAD:
                raise DomainError("avatar_upload", "图片超过大小限制",413)
        try:
            payload=AvatarCreate.model_validate_json(body)
        except ValueError as exc:
            raise DomainError("avatar_input", "请填写人物描述并上传有效图片",422) from exc
        return await app.state.avatars.create(user,payload)

    @app.get("/api/avatars/{aid}")
    async def avatar_status(request: Request,aid: str):
        return await app.state.avatars.status(aid,owner(request))

    @app.post("/api/avatars/{aid}/{operation}")
    async def avatar_control(request: Request,aid: str,operation: str):
        return await app.state.avatars.control(aid,owner(request),operation)

    @app.get("/api/avatars/{aid}/files/{filename:path}")
    async def avatar_asset(request: Request,aid: str,filename: str):
        return FileResponse(app.state.avatars.asset(aid,owner(request),filename))

    @app.post("/api/rooms")
    async def create_room(request: Request, payload: RoomCreate):
        return app.state.rooms.create(owner(request), payload)

    @app.post("/api/rooms/join")
    async def join_room(request: Request, payload: RoomJoin):
        return app.state.rooms.join(owner(request), payload)

    @app.get("/api/rooms/{rid}")
    async def room_view(request: Request, rid: str):
        return app.state.rooms.view(rid, owner(request))

    @app.post("/api/rooms/{rid}/control")
    async def room_control(request: Request, rid: str, payload: RoomControl):
        return app.state.rooms.control(rid, owner(request), payload)

    @app.post("/api/rooms/{rid}/actions", status_code=202)
    async def room_action(request: Request, rid: str, payload: RoomAction):
        action, fresh = app.state.rooms.accept(rid, owner(request), payload)
        if fresh:
            token = MODEL_OWNER.set(action["owner"])
            try:
                app.state.runtime.start(action["id"])
            finally:
                MODEL_OWNER.reset(token)
        return app.state.rooms.receipt(rid, owner(request), action)

    @app.get("/api/rooms/{rid}/actions/{aid}")
    async def room_action_view(request: Request, rid: str, aid: str):
        _, action = app.state.rooms.action(rid, owner(request), aid)
        return app.state.rooms.receipt(rid, owner(request), action)

    @app.post("/api/rooms/{rid}/actions/{aid}/{operation}")
    async def room_action_control(request: Request, rid: str, aid: str, operation: str):
        user = owner(request)
        room, action = app.state.rooms.action(rid, user, aid, control=True)
        if operation == "cancel":
            app.state.runtime.cancel(aid, room["owner"])
        elif operation == "retry":
            app.state.rooms.require_turn(room, user)
            if action["command"].get("actor_id", app.state.store.branches[room["branch_id"]]["state"]["player"]) != app.state.rooms.character(room, user):
                raise DomainError("player_permission", "只能重试当前席位所控制角色的行动", 403)
            token = MODEL_OWNER.set(room["owner"])
            try:
                app.state.runtime.retry(aid, room["owner"])
            finally:
                MODEL_OWNER.reset(token)
        else:
            raise DomainError("room_operation", "不支持的操作", 422)
        return app.state.rooms.receipt(rid, user, action)

    @app.get("/api/rooms/{rid}/memories")
    async def room_memories(request: Request, rid: str, q: str = Query(default="", max_length=240)):
        user = owner(request)
        room = app.state.rooms.get(rid, user)
        state = app.state.store.branches[room["branch_id"]]["state"]
        return {"world_version": state["version"], "records": retrieve(state, app.state.rooms.character(room, user), q, 20, 12000)}

    async def recall_snapshot(state, actor, payload, scope):
        snapshot = deepcopy(state)
        budget = {'calls': 0, 'traces': []}
        service = getattr(app.state.gateway, 'memory', None)
        try:
            async with asyncio.timeout(180):
                found = (await service.recall(snapshot, actor, payload.query, 'recall_' + secrets.token_hex(10),
                                             budget, limit=payload.limit, char_budget=12000, scope=scope) if service else
                         retrieve(snapshot, actor, payload.query, payload.limit, 12000))
        except TimeoutError as exc:
            raise DomainError('memory_timeout', 'Memory retrieval time budget exhausted', 504) from exc
        return {'world_version': snapshot['version'], 'records': found, 'diagnostics': budget['traces']}

    @app.post('/api/rooms/{rid}/recall')
    async def room_recall(request: Request, rid: str, payload: RecallRequest):
        user = owner(request)
        room = app.state.rooms.get(rid, user)
        actor = app.state.rooms.character(room, user)
        token = MODEL_OWNER.set(room['owner'])
        try:
            return await recall_snapshot(app.state.store.branches[room['branch_id']]['state'], actor, payload, room['branch_id'])
        finally:
            MODEL_OWNER.reset(token)

    @app.get("/api/rooms/{rid}/avatars/{aid}")
    async def room_avatar_status(request: Request, rid: str, aid: str):
        host = app.state.rooms.visible_avatar(rid, owner(request), aid)
        value = await app.state.avatars.status(aid, host)
        # Creation descriptions and diagnostics can contain private character material.
        return {k: value[k] for k in ("id", "state", "progress") if k in value}

    @app.get("/api/rooms/{rid}/avatars/{aid}/files/{filename:path}")
    async def room_avatar_asset(request: Request, rid: str, aid: str, filename: str):
        host = app.state.rooms.visible_avatar(rid, owner(request), aid)
        path = app.state.avatars.asset(aid, host, filename)
        if filename == "profile.json":
            return {"character_id": app.state.avatars.record(aid, host)["character_id"]}
        return FileResponse(path)

    @app.get("/api/rooms/{rid}/export")
    async def room_export(request: Request, rid: str):
        value = app.state.rooms.view(rid, owner(request))
        if value["state"] is None:
            raise DomainError("room_character", "请先取得角色席位", 409)
        return Response(json.dumps({"scope": "player_transcript", "view": value["state"]}, ensure_ascii=False, indent=2),
                        media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{rid}-perspective.json"'})

    @app.get("/api/campaigns")
    async def campaigns(request: Request):
        user = owner(request)
        return [{"id": c["id"], "title": c["template"]["title"], "player_name": c["player_name"],
                 "main_branch": c["main_branch"], "created_at": c["created_at"],
                 "world_ref": c["template"].get("world_ref"),
                 "world_version": app.state.store.branches[c["main_branch"]]["state"]["version"]}
                for c in app.state.store.campaigns.values() if c["owner"] == user]

    @app.get('/api/action-modules')
    async def action_modules():
        return app.state.store.action_registry.describe()

    @app.get('/api/check-engines')
    async def check_engines():
        return app.state.store.check_registry.describe()

    @app.post("/api/campaigns", status_code=201)
    async def new_campaign(request: Request, payload: NewCampaign):
        key, fingerprint = None, None
        if payload.request_id is not None:
            key, fingerprint = identity("campaign", owner(request), payload.request_id, payload.model_dump(exclude_none=True))
            existing = receipt(app.state.store.campaigns, key, owner(request), fingerprint)
            if existing is not None:
                return {"id": existing["id"], "branch_id": existing["main_branch"]}
        selected = template
        if payload.story_id:
            story = app.state.store.studio_get("stories", payload.story_id, owner(request))
            report = story.get("test_report", {})
            if report.get("status") != "passed" or report.get("revision") != story["revision"]:
                raise DomainError("story_not_tested", "请先完成当前故事版本的自动测试", 409)
            selected = compile_story(WorldBlueprint.model_validate(story["world_content"]),
                                     StoryBlueprint.model_validate(story["content"]), story["id"], story["revision"],
                                     story.get("origin"))
            selected["world_ref"] = {"id": story["world_id"], "revision": story["world_revision"],
                                     "fingerprint": digest(WorldBlueprint.model_validate(story["world_content"]).model_dump(exclude_none=True, exclude_defaults=True))}
        elif payload.template_id != template["id"]:
            raise DomainError("template_not_found", "世界模板不存在", 404)
        if payload.source_campaign_id:
            if not payload.story_id or not payload.source_branch_id or payload.source_world_version is None:
                raise DomainError("invalid_continuity", "继承存档需要故事、来源分支与版本", 422)
            source_campaign = app.state.store.campaign(payload.source_campaign_id, owner(request))
            source = app.state.store.branch(payload.source_campaign_id, payload.source_branch_id, owner(request))
            selected = carry_world(selected, source, source_campaign, payload.source_world_version)
        elif payload.source_branch_id is not None or payload.source_world_version is not None:
            raise DomainError("invalid_continuity", "请提供来源冒险", 422)
        c = app.state.store.create_campaign(owner(request), selected, payload.player_name.strip() or "旅人",
                                            request_key=key, request_hash=fingerprint)
        return {"id": c["id"], "branch_id": c["main_branch"]}

    @app.get("/api/studio")
    async def studio_library(request: Request):
        user = owner(request)
        return {name: [public_content(v) for v in getattr(app.state.store, name).values() if v["owner"] == user]
                for name in ["worlds", "stories", "jobs"]}

    @app.get("/api/catalog")
    async def starter_catalog():
        return [public_pack(pack) for pack in catalog.values()]

    def package_viewer(request):
        return owner(request) if re.fullmatch(r"[a-f0-9]{64}", request.cookies.get("rpw_session", "")) else None

    @app.get("/api/community")
    async def community(q: str = Query(default="", max_length=100), language: str = Query(default="", max_length=40),
                        tag: str = Query(default="", max_length=32), offset: int = Query(default=0, ge=0),
                        limit: int = Query(default=24, ge=1, le=50)):
        rows = [p for p in app.state.store.publications.values() if p['visibility'] == 'listed']
        rows = [p for p in rows if (not language or language in p['languages']) and (not tag or tag in p['metadata']['tags'])
                and q.casefold() in ' '.join([p['metadata']['title'], p['metadata']['summary'], p['metadata']['author'], *p['metadata']['tags']]).casefold()]
        rows.sort(key=lambda p: (p['created_at'], p['id']), reverse=True)
        return {'total': len(rows), 'items': [public_package(p) for p in rows[offset:offset + limit]]}

    @app.get("/api/studio/packages")
    async def own_packages(request: Request):
        user = owner(request)
        return [public_package(p) for p in app.state.store.publications.values() if p['owner'] == user]

    @app.post("/api/studio/packages", status_code=201)
    async def make_package(request: Request, payload: PackageBuild):
        return public_package(build_package(app.state.studio, app.state.avatars, owner(request), payload))

    async def read_package_upload(request):
        owner(request)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_PACKAGE:
                raise DomainError('upload_limit', '内容包超过32 MiB', 413)
        return bytes(raw)

    @app.post("/api/studio/packages/preview")
    async def preview_package_upload(request: Request):
        return preview_package(read_package(await read_package_upload(request)))

    @app.post("/api/studio/packages/import", status_code=202)
    async def import_package(request: Request, story_keys: Annotated[list[Identifier] | None, Query(max_length=8)] = None):
        raw = await read_package_upload(request)
        return public_content(install_package(app.state.studio, owner(request), raw, PackageInstall(story_keys=story_keys)))

    @app.put("/api/studio/packages/{pid}/visibility")
    async def package_visibility(request: Request, pid: str, payload: PackageVisibility):
        return public_package(set_visibility(app.state.store, owner(request), pid, payload))

    @app.get("/api/community/{pid}")
    async def community_package(request: Request, pid: str):
        return public_package(visible_package(app.state.store, pid, package_viewer(request)))

    @app.get("/api/community/{pid}/download")
    async def download_package(request: Request, pid: str):
        record = visible_package(app.state.store, pid, package_viewer(request))
        return FileResponse(package_path(app.state.store, record['sha256']), media_type='application/zip',
                            filename=f"{record['metadata']['slug']}-{record['metadata']['release']}.narraloom.zip")

    @app.post("/api/community/{pid}/install", status_code=202)
    async def community_install(request: Request, pid: str, payload: PackageInstall):
        user = owner(request)
        record = visible_package(app.state.store, pid, user)
        return public_content(install_package(app.state.studio, user, package_path(app.state.store, record['sha256']).read_bytes(), payload, source_id=pid))

    @app.post("/api/studio/catalog/{key}/install", status_code=202)
    async def install_starter(request: Request, key: str):
        return public_content(install(app.state.studio, owner(request), get_pack(catalog, key)))

    @app.get("/api/studio/imports")
    async def import_library(request: Request):
        user = owner(request)
        return [preview(value) for value in app.state.store.imports.values() if value["owner"] == user]

    @app.post("/api/studio/imports", status_code=201)
    async def upload_import(request: Request, filename: str):
        user, body = owner(request), bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_UPLOAD:
                raise DomainError("upload_limit", "文件超过 8 MiB", 413)
        return preview(receive(app.state.store, user, bytes(body), filename))

    @app.get("/api/studio/imports/{iid}/original")
    async def original_import(request: Request, iid: str):
        record = app.state.store.studio_get("imports", iid, owner(request))
        return FileResponse(app.state.store.journal.root / "imports" / record["sha256"],
                            media_type="application/octet-stream", filename=record["filename"])

    @app.post("/api/studio/imports/{iid}/convert", status_code=202)
    async def convert_import(request: Request, iid: str, payload: ConvertRequest):
        return public_content(submit_conversion(app.state.studio, owner(request), iid, payload.brief, payload.additional_ids, payload.content_language))

    @app.post("/api/studio/worlds", status_code=202)
    async def create_world(request: Request, payload: CreateWorld):
        return public_content(app.state.studio.submit(owner(request), "world", payload.prompt,
                                                     story_prompt=payload.story_prompt, rules_mode=payload.rules_mode,
                                                     living_world=payload.living_world, avatar_id=payload.avatar_id,
                                                     custom_states=payload.custom_states, content_language=payload.content_language,
                                                     creation_preset=payload.creation_preset, request_id=payload.request_id,
                                                     check_engine=payload.check_engine, action_modules=payload.action_modules))

    @app.post("/api/studio/worlds/{wid}/stories", status_code=202)
    async def create_story(request: Request, wid: str, payload: CreateStory):
        return public_content(app.state.studio.submit(owner(request), "story", payload.prompt, world_id=wid,
                                                     custom_states=payload.custom_states, content_language=payload.content_language,
                                                     creation_preset=payload.creation_preset, request_id=payload.request_id))

    @app.post("/api/studio/worlds/{wid}/archive")
    async def archive_world(request: Request, wid: str, archived: bool = True):
        original = app.state.store.studio_get("worlds", wid, owner(request))
        value = {**original, "archived": archived, "updated_at": time.time()}
        app.state.store.studio_save("worlds", value)
        return public_content(value)

    @app.put("/api/studio/worlds/{wid}")
    async def edit_world(request: Request, wid: str, payload: EditWorld):
        original = app.state.store.studio_get("worlds", wid, owner(request))
        if original["revision"] != payload.expected_revision:
            raise DomainError("stale_revision", "世界已在其他页面更新，请刷新后编辑")
        validate_world(payload.content)
        value = {**original, "content": payload.content.model_dump(), "revision": original["revision"] + 1, "updated_at": time.time()}
        return public_content(app.state.store.studio_save("worlds", value))

    @app.put("/api/studio/stories/{sid}")
    async def edit_story(request: Request, sid: str, payload: EditStory):
        original = app.state.store.studio_get("stories", sid, owner(request))
        if original["revision"] != payload.expected_revision:
            raise DomainError("stale_revision", "故事已在其他页面更新，请刷新后编辑")
        validate_story(WorldBlueprint.model_validate(original["world_content"]), payload.content)
        # Reject a full queue before changing the saved revision. No awaits between
        # capacity check, revision save and job submission in this single writer.
        app.state.studio.require_capacity(owner(request))
        value = {**original, "content": payload.content.model_dump(), "revision": original["revision"] + 1,
                 "test_report": {"status": "pending"}, "semantic_review": None, "updated_at": time.time()}
        app.state.store.studio_save("stories", value)
        return public_content(app.state.studio.submit(owner(request), "test", world_id=value["world_id"], story_id=sid))

    @app.post("/api/studio/stories/{sid}/test", status_code=202)
    async def test_story(request: Request, sid: str):
        story = app.state.store.studio_get("stories", sid, owner(request))
        return public_content(app.state.studio.submit(owner(request), "test", world_id=story["world_id"], story_id=sid))

    @app.post("/api/studio/stories/{sid}/repair", status_code=202)
    async def repair_story(request: Request, sid: str, payload: RepairStory):
        story = app.state.store.studio_get("stories", sid, owner(request))
        return public_content(app.state.studio.submit(owner(request), "repair", world_id=story["world_id"],
                                                     story_id=sid, expected_revision=payload.expected_revision))

    @app.get("/api/studio/jobs/{jid}")
    async def creation_status(request: Request, jid: str):
        return public_content(app.state.store.studio_get("jobs", jid, owner(request)))

    @app.post("/api/studio/jobs/{jid}/retry")
    async def retry_creation(request: Request, jid: str):
        app.state.studio.retry(jid, owner(request))
        return public_content(app.state.store.jobs[jid])

    @app.post("/api/studio/jobs/{jid}/cancel")
    async def cancel_creation(request: Request, jid: str):
        app.state.studio.cancel(jid, owner(request))
        return public_content(app.state.store.jobs[jid])

    @app.get("/api/studio/stories/{sid}/export")
    async def export_story(request: Request, sid: str):
        story = app.state.store.studio_get("stories", sid, owner(request))
        data = {"schema_version": "0.2.0", "scope": "creator_story", "world": story["world_content"], "story": story["content"],
                "origin": story.get("origin")}
        return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{sid}.json"'})

    @app.get("/api/campaigns/{cid}/backup")
    async def backup(request: Request, cid: str):
        value = export_campaign(app.state.store, cid, owner(request))
        return Response(json.dumps(value, ensure_ascii=False), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{cid}.rpw.json"'})

    @app.post("/api/backups/{operation}")
    async def restore(request: Request, operation: str):
        user = owner(request); body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BACKUP:
                raise DomainError("backup_limit", "备份超过6MB", 413)
        if operation == "preview":
            return preview_backup(app.state.store, user, body)
        if operation == "restore":
            return restore_campaign(app.state.store, user, body)
        raise DomainError("backup_operation", "不支持的备份操作", 404)

    @app.get("/api/campaigns/{cid}/branches")
    async def branches(request: Request, cid: str):
        app.state.store.campaign(cid, owner(request))
        return [{"id": b["id"], "title": b["title"], "version": b["state"]["version"],
                 "parent_id": b["parent_id"], "fork_version": b["fork_version"]}
                for b in app.state.store.branches.values() if b["campaign_id"] == cid]

    @app.get("/api/campaigns/{cid}/branches/{bid}/view")
    async def view(request: Request, cid: str, bid: str):
        b = app.state.store.branch(cid, bid, owner(request))
        value = project(b["state"])
        value.update({"campaign_id": cid, "branch_id": bid, "branch_title": b["title"],
                      "fork_version": b["fork_version"], "opening": b["state"]["template"]["opening"],
                      "opening_suggestions": b["state"]["template"]["opening_suggestions"],
                      "history": public_history(b["commits"], b["state"]["player"], b["state"]["player"]),
                      "active_actions": [public_action(a) for a in app.state.store.actions.values()
                                         if a["branch_id"] == bid and a["status"] not in {"committed", "cancelled"}
                                         and a["command"]["expected_world_version"] == b["state"]["version"]]})
        return value

    @app.post("/api/campaigns/{cid}/branches", status_code=201)
    async def fork(request: Request, cid: str, payload: ForkRequest):
        b = app.state.store.fork(cid, payload.source_branch_id, owner(request), payload.world_version, payload.title)
        return {"id": b["id"]}

    @app.get("/api/campaigns/{cid}/branches/{bid}/memories")
    async def memories(request: Request, cid: str, bid: str,
                       q: str = Query(default="", max_length=240), limit: int = Query(default=12, ge=1, le=30)):
        branch = app.state.store.branch(cid, bid, owner(request))
        state = branch["state"]
        return {"world_version": state["version"], "records": retrieve(state, state["player"], q, limit, 12000)}

    @app.post('/api/campaigns/{cid}/branches/{bid}/recall')
    async def recall(request: Request, cid: str, bid: str, payload: RecallRequest):
        branch = app.state.store.branch(cid, bid, owner(request))
        return await recall_snapshot(branch['state'], branch['state']['player'], payload, bid)

    @app.post("/api/campaigns/{cid}/branches/{bid}/actions", status_code=202)
    async def action(request: Request, cid: str, bid: str, payload: ActionCommand):
        user = owner(request)
        room = app.state.rooms.active_for(bid)
        existing = app.state.store.actions.get(payload.action_id)
        if existing and existing["owner"] == user and existing.get("submitter") in {None, user}:
            # A later handoff/room closure cannot invalidate this participant's receipt.
            a, fresh = app.state.store.accept(cid, bid, user, payload, existing.get("submitter"), existing.get("room_id"))
        else:
            if room:
                app.state.rooms.require_turn(room, user)
            a, fresh = app.state.store.accept(cid, bid, user, payload, user if room else None, room["id"] if room else None)
        if fresh:
            app.state.runtime.start(a["id"])
        return public_action(a)

    @app.get("/api/actions/{aid}")
    async def action_status(request: Request, aid: str):
        return public_action(app.state.store.action(aid, owner(request)))

    @app.post("/api/actions/{aid}/cancel")
    async def cancel(request: Request, aid: str):
        app.state.runtime.cancel(aid, owner(request))
        return public_action(app.state.store.action(aid, owner(request)))

    @app.post("/api/actions/{aid}/retry")
    async def retry(request: Request, aid: str):
        user = owner(request)
        current = app.state.store.action(aid, user)
        primary = app.state.store.branches[current["branch_id"]]["state"]["player"]
        if current["command"].get("actor_id", primary) != primary:
            raise DomainError("player_permission", "请由该角色的参与者在房间内重试", 403)
        room = app.state.rooms.active_for(current["branch_id"])
        if room:
            app.state.rooms.require_turn(room, user)
        app.state.runtime.retry(aid, user)
        return public_action(app.state.store.action(aid, owner(request)))

    @app.get("/api/actions/{aid}/events")
    async def events(request: Request, aid: str):
        user = owner(request)
        app.state.store.action(aid, user)

        async def stream():
            last = None
            while not await request.is_disconnected():
                a = public_action(app.state.store.action(aid, user))
                encoded = json.dumps(a, ensure_ascii=False)
                if encoded != last:
                    yield "event: state\ndata: " + encoded + "\n\n"
                    last = encoded
                else:
                    yield ": heartbeat\n\n"
                if a["status"] in {"committed", "failed", "cancelled", "interrupted", "recovery_required"}:
                    break
                await asyncio.sleep(.5)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})

    @app.get("/api/campaigns/{cid}/branches/{bid}/export")
    async def export(request: Request, cid: str, bid: str):
        b = app.state.store.branch(cid, bid, owner(request))
        content = json.dumps({"schema_version": "0.1.0", "scope": "player_transcript",
                              "view": project(b["state"]), "history": public_history(b["commits"], b["state"]["player"], b["state"]["player"])},
                             ensure_ascii=False, indent=2)
        return Response(content, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{cid}-{bid}.json"'})

    dist, headless = config.web_dist, config.headless
    if not headless and (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    async def index():
        if headless:
            return {"name": "NarraLoom", "mode": "headless", "openapi": "/openapi.json", "docs": "/docs"}
        if not (dist / "index.html").exists():
            return JSONResponse({"message": "Run npm run build to build the browser client"}, status_code=503)
        return FileResponse(dist / "index.html")

    return app
