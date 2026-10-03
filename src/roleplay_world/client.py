"""Async HTTP client for external applications. Writes are never silently retried.

Persist a Session and PreparedRequest before submitting a creation/action. Reusing
that request recovers its durable receipt without assigning a new request ID.
"""

import asyncio
import hashlib
import json
import math
import os
import tempfile
import uuid
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import unquote

import httpx
from pydantic import BaseModel, Field, TypeAdapter, model_validator

from .content import CreateStory, CreateWorld, EditStory, EditWorld
from .contracts import ActionCommand, Contract, ForkRequest, Identifier, NewCampaign

KINDS = {"world": CreateWorld, "story": CreateStory, "campaign": NewCampaign, "action": ActionCommand}
TERMINAL = {"ready", "committed", "failed", "cancelled", "interrupted", "recovery_required"}
IDENTIFIER = TypeAdapter(Identifier)


def server_url(value: str) -> str:
    url = httpx.URL(value)
    if (url.scheme not in {"http", "https"} or not url.host or url.userinfo
            or url.query or url.fragment or "\\" in value):
        raise ValueError("Use an HTTP(S) server URL without credentials, query or fragment")
    return str(url).rstrip("/") + "/"


def save_private(path: Path, value: dict):
    """Publish complete JSON atomically; filesystem isolation remains host-specific."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="." + path.name + "-", delete=False) as out:
            temporary = Path(out.name)
            json.dump(value, out, ensure_ascii=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class Session(Contract):
    format: Literal["narraloom.session-1"] = "narraloom.session-1"
    server: str
    cookie: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$", repr=False)]

    @model_validator(mode="after")
    def normalize(self):
        self.server = server_url(self.server)
        return self

    @property
    def fingerprint(self):
        return hashlib.sha256(self.cookie.encode()).hexdigest()

    def save(self, path):
        save_private(Path(path), self.model_dump())

    @classmethod
    def load(cls, path):
        return cls.model_validate_json(Path(path).read_text())


class PreparedRequest(Contract):
    format: Literal["narraloom.request-1"] = "narraloom.request-1"
    server: str
    session_fingerprint: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    kind: Literal["world", "story", "campaign", "action"]
    target: tuple[Identifier, ...] = ()
    body: dict = Field(repr=False)

    @model_validator(mode="after")
    def check(self):
        self.server = server_url(self.server)
        if len(self.target) != {"world": 0, "story": 1, "campaign": 0, "action": 2}[self.kind]:
            raise ValueError("Invalid request target")
        payload = KINDS[self.kind].model_validate(self.body)
        if self.kind != "action" and payload.request_id is None:
            raise ValueError("Creation requests need a durable request_id")
        self.body = payload.model_dump(mode="json", exclude_none=True)
        return self

    @property
    def path(self):
        if self.kind == "world":
            return "/api/studio/worlds"
        if self.kind == "story":
            return f"/api/studio/worlds/{self.target[0]}/stories"
        if self.kind == "campaign":
            return "/api/campaigns"
        return f"/api/campaigns/{self.target[0]}/branches/{self.target[1]}/actions"

    @property
    def request_id(self):
        return self.body["action_id" if self.kind == "action" else "request_id"]

    def save(self, path):
        save_private(Path(path), self.model_dump(mode="json"))

    @classmethod
    def load(cls, path):
        return cls.model_validate_json(Path(path).read_text())


class APIError(RuntimeError):
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.body = body if isinstance(body, dict) else {}
        self.code = self.body.get("error", "http_error")
        self.message = self.body.get("message", "Server rejected the request")
        super().__init__(f"{status_code} {self.code}: {self.message}")


class TaskFailed(RuntimeError):
    def __init__(self, kind, snapshot):
        self.kind, self.snapshot = kind, snapshot
        self.task_id, self.status = snapshot["id"], snapshot["status"]
        super().__init__(f"{kind} {self.task_id}: {self.status}")


class WaitTimeout(TimeoutError):
    def __init__(self, kind, task_id, last_snapshot):
        self.kind, self.task_id, self.last_snapshot = kind, task_id, last_snapshot
        super().__init__(f"Stopped waiting for {kind} {task_id}; the server task was not cancelled")


class ProtocolError(RuntimeError):
    pass


class NarraLoomClient:
    def __init__(self, server=None, *, session: Session | None = None,
                 timeout=30, transport: httpx.AsyncBaseTransport | None = None):
        self.server = server_url(server if server is not None else session.server if session is not None else "http://127.0.0.1:18090")
        self._session = session.model_copy(deep=True) if session is not None else None
        if session is not None and session.server != self.server:
            raise ValueError("A session can only be used with its original server URL")
        self._http = httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False, transport=transport)
        self._connected = False
        self._connect_lock = asyncio.Lock()

    async def __aenter__(self):
        try:
            await self.connect()
        except BaseException:
            await self.aclose()
            raise
        return self

    async def __aexit__(self, *_):
        await self.aclose()

    async def aclose(self):
        await self._http.aclose()

    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Connect before preparing requests or saving a session")
        return self._session.model_copy(deep=True)

    def _url(self, path):
        decoded = unquote(path)
        url = httpx.URL(path)
        if (not path.startswith("/") or decoded.startswith("//") or "\\" in decoded
                or not url.is_relative_url or url.query or url.fragment or ".." in decoded.split("/")):
            raise ValueError("Use a server-relative API path; pass query fields through params")
        return httpx.URL(self.server).join(path.lstrip("/"))

    @staticmethod
    def _check(response):
        if not 200 <= response.status_code < 300:
            try:
                body = response.json()
            except ValueError:
                body = {}
            raise APIError(response.status_code, body)
        return response

    async def connect(self):
        async with self._connect_lock:
            if self._connected:
                return self.session
            headers = {"Cookie": "rpw_session=" + self._session.cookie} if self._session is not None else {}
            response = self._check(await self._http.post(self._url("/api/session"), headers=headers))
            try:
                cookie = response.cookies.get("rpw_session")
                restored = Session(server=self.server, cookie=cookie)
                csrf = response.json()["csrf_token"]
                if csrf != hashlib.sha256(("csrf:" + restored.cookie).encode()).hexdigest():
                    raise ValueError("Mismatched session tokens")
                if self._session is not None and restored.cookie != self._session.cookie:
                    raise ValueError("Server replaced a saved session")
            except (ValueError, KeyError, TypeError, httpx.CookieConflict) as exc:
                raise ProtocolError("Server did not preserve the session protocol") from exc
            self._session = restored
            self._http.headers["X-CSRF-Token"] = csrf
            self._connected = True
            return self.session

    async def request(self, method, path, *, json=None, content=None, params=None, raw=False):
        url = self._url(path)  # Validate destination before establishing any session.
        await self.connect()
        if isinstance(json, BaseModel):
            json = json.model_dump(mode="json", exclude_none=True)
        response = self._check(await self._http.request(method, url, json=json, content=content, params=params))
        if raw:
            return response.content
        try:
            return response.json()
        except ValueError as exc:
            raise ProtocolError("Expected a JSON API response") from exc

    def _prepare(self, kind, payload, target=()):
        body = KINDS[kind].model_validate(payload).model_dump(mode="json", exclude_none=True)
        if kind != "action":
            body.setdefault("request_id", "request_" + uuid.uuid4().hex)
        return PreparedRequest(server=self.server, session_fingerprint=self.session.fingerprint,
                               kind=kind, target=target, body=body)

    def prepare_world(self, payload: CreateWorld):
        return self._prepare("world", payload)

    def prepare_story(self, world_id, payload: CreateStory):
        return self._prepare("story", payload, (world_id,))

    def prepare_campaign(self, payload: NewCampaign):
        return self._prepare("campaign", payload)

    def prepare_action(self, campaign_id, branch_id, payload: ActionCommand):
        return self._prepare("action", payload, (campaign_id, branch_id))

    async def submit(self, pending: PreparedRequest):
        pending = PreparedRequest.model_validate(pending.model_dump())
        if pending.server != self.server:
            raise ValueError("A prepared request is bound to its original server and session")
        await self.connect()
        if pending.session_fingerprint != self.session.fingerprint:
            raise ValueError("A prepared request is bound to its original server and session")
        return await self.request("POST", pending.path, json=pending.body)

    async def library(self):
        return await self.request("GET", "/api/studio")

    async def campaigns(self):
        return await self.request("GET", "/api/campaigns")

    async def view(self, campaign_id, branch_id):
        cid, bid = IDENTIFIER.validate_python(campaign_id), IDENTIFIER.validate_python(branch_id)
        return await self.request("GET", f"/api/campaigns/{cid}/branches/{bid}/view")

    async def job(self, job_id):
        return await self.request("GET", f"/api/studio/jobs/{IDENTIFIER.validate_python(job_id)}")

    async def action(self, action_id):
        return await self.request("GET", f"/api/actions/{IDENTIFIER.validate_python(action_id)}")

    async def _wait(self, kind, task_id, timeout, interval):
        if not math.isfinite(timeout) or timeout <= 0 or not math.isfinite(interval) or interval <= 0:
            raise ValueError("Polling timeout and interval must be finite positive seconds")
        last = None
        try:
            async with asyncio.timeout(timeout):
                while True:
                    last = await (self.job(task_id) if kind == "job" else self.action(task_id))
                    if last["status"] in TERMINAL:
                        if last["status"] != ("ready" if kind == "job" else "committed"):
                            raise TaskFailed(kind, last)
                        return last
                    await asyncio.sleep(interval)
        except TimeoutError as exc:
            raise WaitTimeout(kind, task_id, last) from exc

    async def wait_job(self, job_id, *, timeout=1200, interval=.5):
        return await self._wait("job", job_id, timeout, interval)

    async def wait_action(self, action_id, *, timeout=180, interval=.5):
        return await self._wait("action", action_id, timeout, interval)

    async def cancel_job(self, job_id):
        return await self.request("POST", f"/api/studio/jobs/{IDENTIFIER.validate_python(job_id)}/cancel")

    async def retry_job(self, job_id):
        return await self.request("POST", f"/api/studio/jobs/{IDENTIFIER.validate_python(job_id)}/retry")

    async def cancel_action(self, action_id):
        return await self.request("POST", f"/api/actions/{IDENTIFIER.validate_python(action_id)}/cancel")

    async def retry_action(self, action_id):
        return await self.request("POST", f"/api/actions/{IDENTIFIER.validate_python(action_id)}/retry")

    async def edit_world(self, world_id, payload: EditWorld):
        return await self.request("PUT", f"/api/studio/worlds/{IDENTIFIER.validate_python(world_id)}", json=payload)

    async def edit_story(self, story_id, payload: EditStory):
        return await self.request("PUT", f"/api/studio/stories/{IDENTIFIER.validate_python(story_id)}", json=payload)

    async def fork(self, campaign_id, payload: ForkRequest):
        return await self.request("POST", f"/api/campaigns/{IDENTIFIER.validate_python(campaign_id)}/branches", json=payload)

    async def export_story(self, story_id):
        return await self.request("GET", f"/api/studio/stories/{IDENTIFIER.validate_python(story_id)}/export")

    async def backup(self, campaign_id):
        return await self.request("GET", f"/api/campaigns/{IDENTIFIER.validate_python(campaign_id)}/backup")

    async def restore(self, backup):
        return await self.request("POST", "/api/backups/restore", json=backup)
