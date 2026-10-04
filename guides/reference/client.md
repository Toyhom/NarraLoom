# Python client and recovery

[Developer guide](../developers.md) · [HTTP API](api.md)

`roleplay_world.client.NarraLoomClient` ships in the wheel: an async Python 3.11+
HTTP client for backend v0.14+. It uses public APIs and the existing dependencies
for sessions/CSRF, typed requests, polling and saved pending requests. No React is
required; other frontends can use the same HTTP protocol.

```python
import asyncio
from roleplay_world.client import NarraLoomClient, PreparedRequest, Session
from roleplay_world.content import CreateWorld
from roleplay_world.contracts import NewCampaign

async def main():
    async with NarraLoomClient("http://localhost:18090") as client:
        client.session.save("outputs/client/session.json")
        pending = client.prepare_world(CreateWorld(
            prompt="A reading room with a librarian who likes discussing books.",
            creation_preset="scene", content_language="en"))
        pending.save("outputs/client/world.json")  # Persist BEFORE sending.
        job = await client.wait_job((await client.submit(pending))["id"])
        start = client.prepare_campaign(NewCampaign(story_id=job["story_id"], player_name="Visitor"))
        start.save("outputs/client/start.json")
        campaign = await client.submit(start)
        print(await client.view(campaign["id"], campaign["branch_id"]))

asyncio.run(main())
```

Use `prepare_story(world_id, CreateStory(prompt=...))` for another story and
`prepare_action(campaign_id, branch_id, ActionCommand(...))` for an action.
Persist, submit and wait. Every action retains its explicit `action_id` and
`expected_world_version`; stale versions are not silently refreshed and executed.

If the response is lost or your process exits:

```python
async with NarraLoomClient(session=Session.load("outputs/client/session.json")) as client:
    receipt = await client.submit(PreparedRequest.load("outputs/client/world.json"))
    ready = await client.wait_job(receipt["id"])
```

Preparation performs no network operation. A creation request receives one random
`request_id` when none is supplied. Reuse the saved request; preparing a new ID
expresses a new intent. Session files contain cookies and belong in private,
ignored runtime storage. Request files contain prompts/actions and a session
fingerprint, not the cookie. Requests bind to their original user and exact
normalized server URL, including port/path. They are not redirected to another
server. Use content packages/backups for migration. Files use atomic replacement.

| Operation | Meaning |
| --- | --- |
| `submit(original)` | Recover the same job/campaign/action without restarting it |
| `wait_job` / `wait_action` | Poll until ready/committed; local timeout or coroutine cancellation does not cancel server work |
| `retry_job` / `retry_action` | Explicit execution retry, subject to revision/version/permission checks |
| `cancel_job` / `cancel_action` | Explicit server cancellation; committed actions cannot be cancelled |

Cancelled creation jobs may be retried. Action retries support failed/interrupted
states; cancelled actions remain cancelled. `recovery_required` needs storage
recovery and receipt lookup, not a fresh ID.

`APIError` exposes `status_code/code/message/body`, including stable conflict and
revision codes. `TaskFailed` exposes `kind/task_id/status/snapshot`.
`WaitTimeout` exposes `kind/task_id/last_snapshot` for later waiting. HTTPX
transport exceptions propagate: the server may already have accepted the request.
`ProtocolError` reports invalid session/JSON behavior without replacing identity.

Convenience methods also cover `library/campaigns/view/job/action`,
`edit_world/edit_story`, `fork/export_story/backup/restore`.
Requests reuse public Pydantic types; results are public JSON. Edits keep
`expected_revision` and do not acquire creation idempotency. If an edit response
is lost, query current revisions and jobs before proceeding; do not simply
increment the revision and repeat it.

Use `request(method, path, json=..., content=..., params=..., raw=False)` for
other APIs: models, rooms, decisions and native packages. `json` accepts models
or dictionaries, `raw=True` returns bytes. Paths must be server-relative.
Redirects and automatic write retries are disabled. Other languages can use the same HTTP API and generated schemas.

`await client.recall(campaign_id, branch_id, query, limit=8)` retrieves source records using the configured memory policy. It returns the snapshot's `world_version`, records and diagnostics. Hybrid mode may call an embedding service; it leaves the campaign unchanged. See [memory retrieval](memory.md).

```bash
python examples/headless.py --world 'A small reading room' --preset scene --language en
python examples/headless.py --resume
python examples/headless.py --retry
python scripts/verify.py --distribution
python scripts/check_distribution.py --output outputs/validation/my-sdk-check \
  --sdk-live --live-models-config configs/models.local.json --secrets-root secrets
```

The example persists each stage of creation → playtest → campaign → action.
Pending work takes precedence over new CLI text; `--resume` prints an existing
receipt when already complete. Legacy session files remain readable. Distribution
checks exercise actual restarts and model-free recovery. Live mode adds two
stories in one generated world, automatic playtests, interaction and backup
restoration. CPU tests inject lost responses/write acknowledgements, timeout and
local cancellation, and cover conflicts, ownership and changed source revisions.
