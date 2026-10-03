"""Read-only release snapshot: never acquire a writer, recover a tail or change job status."""

import json
from pathlib import Path

from roleplay_world.journal import digest
from roleplay_world.store import Store


def snapshot(root: Path):
    raw = (root / "journal.jsonl").read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise RuntimeError("Journal has an incomplete frame; leave the live writer alone")
    store = Store.__new__(Store)
    libraries = ("worlds", "stories", "jobs", "imports", "avatars", "rooms", "publications")
    for name in ("campaigns", "branches", "actions", *libraries):
        setattr(store, name, {})
    previous = "0" * 64
    for line in raw.splitlines():
        frame = json.loads(line)
        if frame["previous"] != previous or digest([previous, frame["body"]]) != frame["checksum"]:
            raise RuntimeError("Journal chain verification failed")
        store._apply(frame["body"])
        previous = frame["checksum"]
    busy = [a["id"] for a in store.actions.values() if a["status"] in {"accepted", "planning", "characters", "narrating"}]
    busy += [j["id"] for j in store.jobs.values() if j["status"] in {"queued", "generating_world", "generating_story", "testing"}]
    if busy:
        raise RuntimeError(f"{len(busy)} actions/creation jobs are active; do not restart")
    return {"bytes": len(raw), "last_checksum": previous,
            "campaigns": {k: digest(v) for k, v in store.campaigns.items()},
            "branches": {k: digest(v["state"]) for k, v in store.branches.items()},
            "libraries": {name: digest(getattr(store, name)) for name in libraries}}
