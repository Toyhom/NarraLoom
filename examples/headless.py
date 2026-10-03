"""Create/play/resume through the packaged SDK; persist every request before sending."""

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from roleplay_world.client import APIError, NarraLoomClient, PreparedRequest, Session, save_private
from roleplay_world.content import CreateWorld
from roleplay_world.contracts import ActionCommand, NewCampaign


async def run(args):
    saved = json.loads(args.session_file.read_text()) if args.session_file.exists() else {}
    identity = (Session.model_validate(saved["session"]) if saved.get("session") else
                Session(server=saved["url"], cookie=saved["cookie"]) if saved.get("cookie") else None)
    async with NarraLoomClient(args.url, session=identity) as client:
        # Legacy session files remain readable; new files retain every pending request.
        saved["session"] = client.session.model_dump()
        for key in ("cookie", "url"):
            saved.pop(key, None)

        def persist():
            save_private(args.session_file, saved)

        persist()
        if not saved.get("flow") and saved.get("job_id"):
            saved["flow"] = {"phase": "job", "job_id": saved.pop("job_id"),
                             "intent": {"text": args.action, "mode": args.mode}}
        elif not saved.get("flow") and saved.get("last_command") and saved.get("campaign"):
            command = ActionCommand.model_validate(saved.pop("last_command"))
            try:
                previous = await client.action(command.action_id)
            except APIError as exc:
                if exc.status_code != 404:
                    raise
                previous = {"status": "not_received"}
            if previous["status"] != "committed":
                campaign = saved["campaign"]
                saved["flow"] = {"phase": "action", "request": client.prepare_action(
                    campaign["id"], campaign["branch_id"], command).model_dump(mode="json")}
            else:
                saved["last_action_id"] = command.action_id

        if not saved.get("flow"):
            if args.resume or args.retry:
                if saved.get("last_action_id"):
                    print_result(await client.action(saved["last_action_id"]))
                else:
                    print("No pending workflow in this session.")
                persist()
                return
            saved["flow"] = {"phase": "world" if args.world else "campaign" if not saved.get("campaign") else "action",
                             "intent": {"text": args.action, "mode": args.mode}}
            if args.world:
                saved["flow"]["request"] = client.prepare_world(CreateWorld(
                    prompt=args.world, story_prompt=args.story, rules_mode="none",
                    content_language=args.language, creation_preset=args.preset)).model_dump(mode="json")
        persist()

        while saved.get("flow"):
            flow = saved["flow"]
            if flow["phase"] == "world":
                job = await client.submit(PreparedRequest.model_validate(flow["request"]))
                flow.update(phase="job", job_id=job["id"])
                flow.pop("request", None)
            elif flow["phase"] == "job":
                if args.retry:
                    current = await client.job(flow["job_id"])
                    if current["status"] in {"failed", "cancelled", "interrupted"}:
                        await client.retry_job(current["id"])
                job = await client.wait_job(flow["job_id"], timeout=args.timeout)
                flow.update(phase="campaign", story_id=job["story_id"])
                flow.pop("job_id")
            elif flow["phase"] == "campaign":
                if "request" not in flow:
                    flow["request"] = client.prepare_campaign(NewCampaign(
                        player_name="Traveler", story_id=flow.get("story_id"))).model_dump(mode="json")
                    persist()
                saved["campaign"] = await client.submit(PreparedRequest.model_validate(flow["request"]))
                flow.update(phase="action")
                flow.pop("request")
            elif flow["phase"] == "action":
                campaign = saved["campaign"]
                if "request" not in flow:
                    view = await client.view(campaign["id"], campaign["branch_id"])
                    flow["request"] = client.prepare_action(campaign["id"], campaign["branch_id"], ActionCommand(
                        action_id="cli_" + uuid.uuid4().hex, expected_world_version=view["world_version"],
                        **flow["intent"])).model_dump(mode="json")
                    persist()
                receipt = await client.submit(PreparedRequest.model_validate(flow["request"]))
                if args.retry and receipt["status"] in {"failed", "interrupted"}:
                    await client.retry_action(receipt["id"])
                result = await client.wait_action(receipt["id"], timeout=args.timeout)
                saved.update(last_action_id=receipt["id"], flow=None)
                persist()
                print_result(result)
            else:
                raise ValueError("Unknown saved workflow phase")
            persist()
        print("Private session saved to", args.session_file)


def print_result(action):
    for segment in action.get("result", {}).get("segments", []):
        print(segment.get("speaker_name", "Narrator") + ": " + segment["text"])
    print("Action:", action["id"], action["status"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18090")
    parser.add_argument("--session-file", type=Path, default=Path("outputs/headless/session.local.json"))
    parser.add_argument("--world", help="Create and automatically playtest a world and its first story")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--preset", choices=["scene", "story", "adventure"], default="adventure")
    parser.add_argument("--story", default="A short encounter that gives the player meaningful choices.")
    parser.add_argument("--action", default="我观察周围的环境。")
    parser.add_argument("--mode", choices=["act", "say", "wait", "ooc"], default="act")
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--resume", action="store_true", help="Finish saved work or show its receipt; do not start another action")
    parser.add_argument("--retry", action="store_true", help="Explicitly retry a saved failed/cancelled/interrupted task")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
