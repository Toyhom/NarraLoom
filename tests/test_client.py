import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from test_content_preferences import SceneFixture

from roleplay_world.app import create_app
from roleplay_world.client import (
    APIError,
    NarraLoomClient,
    PreparedRequest,
    ProtocolError,
    Session,
    TaskFailed,
    WaitTimeout,
)
from roleplay_world.config import AppConfig
from roleplay_world.content import CreateStory, CreateWorld, EditStory, EditWorld
from roleplay_world.contracts import ActionCommand, ForkRequest, NewCampaign


class LoseResponse(httpx.AsyncBaseTransport):
    def __init__(self, app):
        self.inner = httpx.ASGITransport(app=app)
        self.drop_path = None

    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        if request.method == "POST" and request.url.path == self.drop_path:
            self.drop_path = None
            await response.aread()
            await response.aclose()
            raise httpx.ReadError("Simulated lost response after durable acceptance")
        return response

    async def aclose(self):
        await self.inner.aclose()


def test_sdk_creation_action_lost_responses_and_restart(tmp_path):
    async def run():
        config = AppConfig(workspace_root=tmp_path)
        gateway = SceneFixture()
        app = create_app(config=config, gateway=gateway)
        transport = LoseResponse(app)
        async with app.router.lifespan_context(app), NarraLoomClient(transport=transport) as client:
            client.session.save(tmp_path / "session.json")
            pending = client.prepare_world(CreateWorld(prompt="A room in the rain", content_language="en", creation_preset="scene"))
            pending.save(tmp_path / "world.json")
            assert client.session.cookie not in repr(client.session) + repr(pending)
            transport.drop_path = pending.path
            with pytest.raises(httpx.ReadError):
                await client.submit(pending)
            recovered = await client.submit(PreparedRequest.load(tmp_path / "world.json"))
            job = await client.wait_job(recovered["id"], interval=.01)
            assert len(app.state.store.worlds) == len(app.state.store.stories) == 1
            assert "request_hash" not in job
            assert sum(role == "world_builder" for role, _, _ in gateway.calls) == 1

            second_request = client.prepare_story(job["world_id"], CreateStory(prompt="Another visit after the rain"))
            transport.drop_path = second_request.path
            with pytest.raises(httpx.ReadError):
                await client.submit(second_request)
            second = await client.submit(second_request)
            second = await client.wait_job(second["id"], interval=.01)
            assert second["world_id"] == job["world_id"] and second["story_id"] != job["story_id"]
            exported = await client.export_story(job["story_id"])
            assert exported["scope"] == "creator_story"

            start = client.prepare_campaign(NewCampaign(story_id=job["story_id"], player_name="Visitor"))
            start.save(tmp_path / "campaign.json")
            transport.drop_path = start.path
            with pytest.raises(httpx.ReadError):
                await client.submit(start)
            campaign = await client.submit(start)
            cid, bid = campaign["id"], campaign["branch_id"]
            view = await client.view(cid, bid)
            action = client.prepare_action(cid, bid, ActionCommand(action_id="sdk_action", expected_world_version=0,
                                                                   text="Hello, Robin", mode="say"))
            action.save(tmp_path / "action.json")
            transport.drop_path = action.path
            with pytest.raises(httpx.ReadError):
                await client.submit(action)
            result = await client.submit(action)
            committed = await client.wait_action(result["id"], interval=.01)
            final_view = await client.view(cid, bid)
            assert final_view["world_version"] == view["world_version"] + 1
            assert "secret-marker-741" not in json.dumps(final_view)
            backup = await client.backup(cid)
            assert "request_hash" not in backup["campaign"]
            fork = await client.fork(cid, ForkRequest(source_branch_id=bid, world_version=0, title="Before"))
            assert (await client.view(cid, fork["id"]))["world_version"] == 0
            session = client.session
            calls = len(gateway.calls)

        # New app and new HTTP client recover only from public session/request files.
        app = create_app(config=config, gateway=gateway)
        async with app.router.lifespan_context(app), NarraLoomClient(
            session=Session.load(tmp_path / "session.json"), transport=httpx.ASGITransport(app=app)
        ) as client:
            assert (await client.submit(PreparedRequest.load(tmp_path / "world.json")))["id"] == job["id"]
            assert await client.submit(PreparedRequest.load(tmp_path / "campaign.json")) == campaign
            repeated = await client.submit(PreparedRequest.load(tmp_path / "action.json"))
            assert repeated["result"] == committed["result"]
            assert await client.view(cid, bid) == final_view
            assert len(gateway.calls) == calls
            restored = await client.restore(backup)
            assert restored["id"] != cid
            assert (await client.view(restored["id"], restored["branch_id"]))["world_version"] == 1
            assert session.cookie == client.session.cookie
    asyncio.run(run())


def test_creation_keys_check_payload_owner_and_old_revision(tmp_path):
    async def run():
        app = create_app(config=AppConfig(workspace_root=tmp_path), gateway=SceneFixture())
        async with app.router.lifespan_context(app), NarraLoomClient(transport=httpx.ASGITransport(app=app)) as client:
            request = client.prepare_world(CreateWorld(request_id="shared_key", prompt="A room in the rain",
                                                       content_language="en", creation_preset="scene"))
            job = await client.submit(request)
            job = await client.wait_job(job["id"], interval=.01)
            library = await client.library()
            world, story = library["worlds"][0], library["stories"][0]
            campaign_request = client.prepare_campaign(NewCampaign(request_id="campaign_key", story_id=story["id"]))
            campaign = await client.submit(campaign_request)
            world["content"]["title"] += " revision"
            await client.edit_world(world["id"], EditWorld(expected_revision=1, content=world["content"]))
            assert (await client.submit(request))["id"] == job["id"]
            # A repeated start recovers the pinned campaign even if its source is currently untested.
            internal = app.state.store.stories[story["id"]]
            app.state.store.studio_save("stories", {**deepcopy(internal), "test_report": {"status": "failed"}})
            assert await client.submit(campaign_request) == campaign
            for changed in (
                client.prepare_world(CreateWorld(request_id="shared_key", prompt="A different room", content_language="en", creation_preset="scene")),
                client.prepare_story(world["id"], CreateStory(request_id="shared_key", prompt="Another scene")),
                client.prepare_campaign(NewCampaign(request_id="campaign_key", story_id=story["id"], player_name="Other")),
            ):
                with pytest.raises(APIError) as err:
                    await client.submit(changed)
                assert err.value.status_code == 409 and err.value.code == "request_id_conflict"
            async with NarraLoomClient(transport=httpx.ASGITransport(app=app)) as other:
                with pytest.raises(ValueError, match="original server and session"):
                    await other.submit(request)
                copied = other.prepare_world(CreateWorld.model_validate(request.body))
                own = await other.submit(copied)
                await other.wait_job(own["id"], interval=.01)
                assert own["id"] != job["id"]
                with pytest.raises(APIError) as err:
                    await other.job(job["id"])
                assert err.value.status_code == 404
            edit = await client.edit_story(story["id"], EditStory(expected_revision=1, content=story["content"]))
            await client.wait_job(edit["id"], interval=.01)
            with pytest.raises(APIError) as err:
                await client.edit_story(story["id"], EditStory(expected_revision=1, content=story["content"]))
            assert err.value.code == "stale_revision"
    asyncio.run(run())


def test_wait_timeout_cancellation_and_receipt_do_not_restart_jobs(tmp_path):
    class Slow(SceneFixture):
        async def generate(self, *args, **kwargs):
            await asyncio.Event().wait()

    async def run():
        config = AppConfig(workspace_root=tmp_path)
        app = create_app(config=config, gateway=Slow())
        async with app.router.lifespan_context(app), NarraLoomClient(transport=httpx.ASGITransport(app=app)) as client:
            pending = client.prepare_world(CreateWorld(prompt="A slow creation", creation_preset="scene", content_language="en"))
            first = await client.submit(pending)
            second = await client.submit(client.prepare_world(CreateWorld(prompt="Another slow creation")))
            with pytest.raises(APIError) as error:
                await client.submit(client.prepare_world(CreateWorld(prompt="Over the queue limit")))
            assert error.value.code == "studio_busy"
            assert (await client.submit(pending))["id"] == first["id"]
            with pytest.raises(WaitTimeout) as error:
                await client.wait_job(first["id"], timeout=.04, interval=.01)
            assert error.value.task_id == first["id"] and error.value.last_snapshot
            assert (await client.job(first["id"]))["status"] == "generating_world"
            wait = asyncio.create_task(client.wait_job(first["id"], interval=.01))
            await asyncio.sleep(.02)
            wait.cancel()
            with pytest.raises(asyncio.CancelledError):
                await wait
            assert (await client.job(first["id"]))["status"] == "generating_world"
            await client.cancel_job(first["id"])
            with pytest.raises(TaskFailed) as error:
                await client.wait_job(first["id"])
            assert error.value.status == "cancelled"
            assert (await client.submit(pending))["status"] == "cancelled"
            assert first["id"] not in app.state.studio.tasks or app.state.studio.tasks[first["id"]].cancelling()
            await client.cancel_job(second["id"])
            session = client.session
        app = create_app(config=config, gateway=SceneFixture())
        async with app.router.lifespan_context(app), NarraLoomClient(session=session, transport=httpx.ASGITransport(app=app)) as client:
            assert (await client.submit(pending))["status"] == "cancelled"
            await client.retry_job(first["id"])
            assert (await client.wait_job(first["id"], interval=.01))["status"] == "ready"
    asyncio.run(run())


def test_no_credentials_or_requests_follow_redirects_or_change_server(tmp_path):
    async def run():
        seen = []
        cookie = "a" * 64
        def transport(request):
            seen.append(request)
            return httpx.Response(307, headers={"Location": "https://unrelated.invalid/steal"})
        session = Session(server="http://localhost:18090", cookie=cookie)
        with pytest.raises(ValueError, match="original server"):
            NarraLoomClient("http://localhost:18091", session=session)
        with pytest.raises(ValueError):
            NarraLoomClient("https://user:secret@localhost")
        async with httpx.AsyncClient():
            client = NarraLoomClient(session=session, server=session.server, transport=httpx.MockTransport(transport))
            try:
                for bad in ("https://unrelated.invalid/", "//unrelated.invalid", "/%2fother.invalid", "/../api", "/a\\b"):
                    with pytest.raises(ValueError):
                        await client.request("GET", bad)
                assert seen == []
                with pytest.raises(APIError) as error:
                    await client.connect()
                assert error.value.status_code == 307
                assert len(seen) == 1 and seen[0].url.host == "localhost"
            finally:
                await client.aclose()
        session.save(tmp_path / "session.json")
        assert Session.load(tmp_path / "session.json") == session
        assert not list(tmp_path.glob(".session.json-*"))
    asyncio.run(run())


def test_saved_session_replacement_is_an_explicit_error():
    async def run():
        import hashlib
        original, replacement = "a" * 64, "b" * 64
        def transport(request):
            return httpx.Response(200, headers={"set-cookie": f"rpw_session={replacement}; Path=/; HttpOnly"},
                                  json={"csrf_token": hashlib.sha256(("csrf:" + replacement).encode()).hexdigest()})
        client = NarraLoomClient(session=Session(server="http://localhost:18090", cookie=original),
                                transport=httpx.MockTransport(transport))
        with pytest.raises(ProtocolError):
            async with client:
                pass
        assert client.session.cookie == original
    asyncio.run(run())


def test_stale_action_duplicate_cancel_and_retry_are_explicit(tmp_path):
    async def run():
        app = create_app(config=AppConfig(workspace_root=tmp_path), gateway=SceneFixture())
        async with app.router.lifespan_context(app), NarraLoomClient(transport=httpx.ASGITransport(app=app)) as client:
            campaign = await client.submit(client.prepare_campaign(NewCampaign()))
            cid, bid = campaign["id"], campaign["branch_id"]
            command = ActionCommand(action_id="note", expected_world_version=0, mode="ooc", text="Remember",
                                    note_record={"id": "note_1", "text": "A private memory", "kind": "note"})
            pending = client.prepare_action(cid, bid, command)
            await client.submit(pending)
            result = await client.wait_action("note", interval=.01)
            assert (await client.submit(pending))["result"] == result["result"]
            with pytest.raises(APIError) as error:
                await client.cancel_action("note")
            assert error.value.code == "already_committed"
            with pytest.raises(APIError) as error:
                await client.submit(client.prepare_action(cid, bid, command.model_copy(update={"action_id": "stale"})))
            assert error.value.code == "stale_world_version"
            assert (await client.view(cid, bid))["world_version"] == 1
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["world", "campaign"])
def test_creation_receipt_recovers_after_uncertain_durable_write(tmp_path, kind):
    async def run():
        config = AppConfig(workspace_root=tmp_path)
        gateway = SceneFixture()
        app = create_app(config=config, gateway=gateway)
        async with app.router.lifespan_context(app), NarraLoomClient(transport=httpx.ASGITransport(app=app)) as client:
            pending = (client.prepare_world(CreateWorld(prompt="A room in the rain", creation_preset="scene", content_language="en"))
                       if kind == "world" else client.prepare_campaign(NewCampaign()))
            original_append = app.state.store.journal.append
            def uncertain(record):
                original_append(record)
                app.state.store.journal.poisoned = True
                raise OSError("Durable write completed but acknowledgement was lost")
            app.state.store.journal.append = uncertain
            with pytest.raises(APIError) as error:
                await client.submit(pending)
            assert error.value.code == "recovery_required"
            with pytest.raises(APIError) as error:
                await client.submit(pending)
            assert error.value.code == "recovery_required"
            session = client.session
        assert gateway.calls == []
        app = create_app(config=config, gateway=gateway)
        async with app.router.lifespan_context(app), NarraLoomClient(session=session, transport=httpx.ASGITransport(app=app)) as client:
            result = await client.submit(pending)
            assert gateway.calls == []
            if kind == "world":
                assert result["status"] == "interrupted"
                await client.retry_job(result["id"])
                await client.wait_job(result["id"], interval=.01)
                assert len(app.state.store.worlds) == 1
            else:
                assert len(await client.campaigns()) == 1
    asyncio.run(run())


@pytest.mark.parametrize("drop", ["campaign", "action"])
def test_headless_example_resumes_saved_work_without_another_action(tmp_path, monkeypatch, drop):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location("headless_example", Path(__file__).resolve().parents[1] / "examples/headless.py")
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)

    class DropOne(LoseResponse):
        failed = False
        async def handle_async_request(self, request):
            matches = request.url.path == "/api/campaigns" if drop == "campaign" else request.url.path.endswith("/actions")
            if matches and request.method == "POST" and not self.failed:
                self.failed = True
                self.drop_path = request.url.path
            return await super().handle_async_request(request)

    async def run():
        gateway = SceneFixture()
        app = create_app(config=AppConfig(workspace_root=tmp_path / "server"), gateway=gateway)
        transport = DropOne(app)
        monkeypatch.setattr(example, "NarraLoomClient", lambda *a, **kw: NarraLoomClient(*a, **kw, transport=transport))
        args = SimpleNamespace(url="http://127.0.0.1:18090", session_file=tmp_path / "client.json",
                               world=None, story="", preset="scene", language="en", action="Explain the rules",
                               mode="ooc", timeout=10, resume=False, retry=False)
        async with app.router.lifespan_context(app):
            with pytest.raises(httpx.ReadError):
                await example.run(args)
            pending = json.loads(args.session_file.read_text())
            assert pending["flow"]["request"]["kind"] == drop
            args.resume = True
            await example.run(args)
            saved = json.loads(args.session_file.read_text())
            assert saved["flow"] is None and len(app.state.store.campaigns) == 1
            assert len(app.state.store.actions) == 1
            calls = len(gateway.calls)
            await example.run(args)
            assert len(app.state.store.actions) == 1 and len(gateway.calls) == calls
    asyncio.run(run())


def test_sdk_failed_action_requires_explicit_retry(tmp_path):
    class Flaky(SceneFixture):
        fail = False
        async def generate(self, *a, **kw):
            if self.fail:
                self.fail = False
                raise RuntimeError("Injected inference failure")
            return await super().generate(*a, **kw)

    async def run():
        gateway = Flaky()
        app = create_app(config=AppConfig(workspace_root=tmp_path), gateway=gateway)
        async with app.router.lifespan_context(app), NarraLoomClient(transport=httpx.ASGITransport(app=app)) as client:
            campaign = await client.submit(client.prepare_campaign(NewCampaign()))
            pending = client.prepare_action(campaign["id"], campaign["branch_id"], ActionCommand(
                action_id="retry_sdk", expected_world_version=0, mode="ooc", text="Explain the rules"))
            gateway.fail = True
            await client.submit(pending)
            with pytest.raises(TaskFailed) as error:
                await client.wait_action("retry_sdk", interval=.01)
            assert error.value.status == "failed"
            calls = len(gateway.calls)
            assert (await client.submit(pending))["status"] == "failed"
            assert len(gateway.calls) == calls
            assert (await client.view(campaign["id"], campaign["branch_id"]))["world_version"] == 0
            await client.retry_action("retry_sdk")
            assert (await client.wait_action("retry_sdk", interval=.01))["status"] == "committed"
            assert (await client.view(campaign["id"], campaign["branch_id"]))["world_version"] == 1
    asyncio.run(run())
