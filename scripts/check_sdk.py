"""External SDK acceptance; --resume verifies durable receipts after a server restart."""

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from roleplay_world.client import NarraLoomClient, PreparedRequest, Session, save_private
from roleplay_world.content import CreateStory, CreateWorld
from roleplay_world.contracts import ActionCommand, NewCampaign


async def run(args):
    folder = args.output.resolve()
    if args.resume:
        report = json.loads((folder / "report.json").read_text())
        if report["status"] != "passed":
            raise ValueError("Recovery acceptance requires a completed initial run")
        session = Session.load(folder / "session.local.json")
    else:
        folder.mkdir(parents=True, exist_ok=False)
        report = {"status": "running", "mode": "test_fixture" if args.fixture else "live_models", "checks": []}
        session = None

    def persist():
        save_private(folder / "report.json", report)

    persist()

    async with NarraLoomClient(args.url, session=session) as client:
        client.session.save(folder / "session.local.json")
        async def submit(name, pending):
            pending.save(folder / f"{name}.json")
            return await client.submit(pending)

        if args.resume:
            before_usage = await client.request("GET", "/api/settings/usage")
            before_library = await client.library()
            before_campaigns = await client.campaigns()
            for name, expected in report["receipts"].items():
                recovered = await client.submit(PreparedRequest.load(folder / f"{name}.json"))
                if name == "action":
                    assert recovered["result"] == expected["result"]
                else:
                    assert recovered["id"] == expected["id"]
            view = await client.view(report["campaign"]["id"], report["campaign"]["branch_id"])
            assert view == json.loads((folder / "view.json").read_text())
            assert await client.library() == before_library
            assert await client.campaigns() == before_campaigns
            assert await client.request("GET", "/api/settings/usage") == before_usage
            report["checks"].append("restart_receipts_state_and_usage_unchanged")
        else:
            story_id = None
            report["receipts"] = {}
            if not args.fixture:
                created = await submit("world", client.prepare_world(CreateWorld(
                    prompt="A small neighborhood reading room with one resident librarian who enjoys talking about books.",
                    story_prompt="A visitor and the librarian discuss choosing something to read on a rainy afternoon.",
                    creation_preset="scene", content_language="en")))
                report["receipts"]["world"] = {"id": created["id"]}
                persist()
                world = await client.wait_job(created["id"])
                report["receipts"]["world"] = {"id": world["id"]}
                story_id = world["story_id"]
                second = await submit("story", client.prepare_story(world["world_id"], CreateStory(
                    prompt="A different visit: talk with the same librarian about favorite travel stories.",
                    creation_preset="scene", content_language="en")))
                report["receipts"]["story"] = {"id": second["id"]}
                persist()
                second = await client.wait_job(second["id"])
                report["receipts"]["story"] = {"id": second["id"]}
                assert second["world_id"] == world["world_id"] and second["story_id"] != story_id
                library = await client.library()
                reports = [s["test_report"] for s in library["stories"]]
                assert len(reports) == 2 and all(r["status"] == "passed" and r["mode"] == "live_models" for r in reports)
                report["content_test_steps"] = [len(r["steps"]) for r in reports]
                save_private(folder / "library.json", library)
                save_private(folder / "creator-export.json", await client.export_story(story_id))
                report["checks"].append("native_world_two_stories_and_automatic_playtests")
            campaign = await submit("campaign", client.prepare_campaign(NewCampaign(story_id=story_id, player_name="SDK visitor")))
            report["campaign"] = campaign
            report["receipts"]["campaign"] = campaign
            view = await client.view(campaign["id"], campaign["branch_id"])
            pending = client.prepare_action(campaign["id"], campaign["branch_id"], ActionCommand(
                action_id="sdk_" + uuid.uuid4().hex, expected_world_version=view["world_version"],
                text="I give the tools to the captain." if args.fixture else "Hello! What do you enjoy about this reading room?",
                mode="act" if args.fixture else "say"))
            action = await submit("action", pending)
            result = await client.wait_action(action["id"])
            report["receipts"]["action"] = {"result": result["result"]}
            assert (await client.submit(pending))["result"] == result["result"]
            view = await client.view(campaign["id"], campaign["branch_id"])
            assert view["world_version"] == 1
            save_private(folder / "view.json", view)
            backup = await client.backup(campaign["id"])
            restored = await client.restore(backup)
            restored_view = await client.view(restored["id"], restored["branch_id"])
            assert restored_view["campaign_id"] == restored["id"] and restored_view["branch_id"] == restored["branch_id"]
            assert {k: v for k, v in restored_view.items() if k not in {"campaign_id", "branch_id"}} == {
                k: v for k, v in view.items() if k not in {"campaign_id", "branch_id"}}
            report["checks"].append("sdk_action_dedup_backup_and_restore")
        report["status"] = "passed"
        save_private(folder / "report.json", report)
        print(json.dumps({"status": report["status"], "mode": report["mode"], "checks": report["checks"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18090")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture", action="store_true", help="Use the external deterministic adapter instead of content generation")
    parser.add_argument("--resume", action="store_true", help="Recover existing receipts only, without creating content or actions")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except BaseException as exc:
        # Preserve complete earlier receipts/session and identify the failed run.
        if args.output.is_dir():
            save_private(args.output / "failure.json", {"error_type": type(exc).__name__})
        raise


if __name__ == "__main__":
    main()
