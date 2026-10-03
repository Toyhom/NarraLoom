"""Pinned, reviewed community adaptations. Only local typed content is installed."""

import json
from copy import deepcopy
from pathlib import Path

from .content import StoryBlueprint, WorldBlueprint, validate_story
from .contracts import DomainError
from .journal import digest

ROOT = Path(__file__).parent / "builtin/starters"


def load_catalog():
    packs = {}
    for path in sorted(ROOT.glob("*.json")):
        pack = json.loads(path.read_text())
        world = WorldBlueprint.model_validate(pack["world"])
        story = StoryBlueprint.model_validate(pack["story"])
        validate_story(world, story)
        if path.stem != pack["id"] or pack["id"] in packs:
            raise ValueError("Catalog IDs must be unique and match filenames")
        pack["digest"] = digest(pack)
        packs[pack["id"]] = pack
    return packs


def get_pack(catalog, key):
    if key not in catalog:
        raise DomainError("not_found", "没有找到这份社区剧本", 404)
    return deepcopy(catalog[key])


def public_pack(pack):
    """The shelf advertises premise and attribution, never secret facts or plot answers."""
    return {**{k: deepcopy(pack[k]) for k in ["id", "version", "title", "summary", "source", "adaptation"]},
            "genre": pack["world"]["genre"], "locations": len(pack["world"]["locations"]),
            "characters": len(pack["world"]["characters"])}


def install(studio, owner, pack):
    # One durable install per owner and exact package content. A failed HTTP response
    # or restart never duplicates the imported world or certifies it prematurely.
    key = digest({"owner": owner, "id": pack["id"], "digest": pack["digest"]})[:24]
    jid, wid, sid = "catalog_" + key, "world_" + key, "story_" + key
    if jid in studio.store.jobs:
        return studio.store.studio_get("jobs", jid, owner)
    studio.require_capacity(owner)
    import time

    created = time.time()
    origin = {k: deepcopy(pack[k]) for k in ["id", "version", "digest", "source", "adaptation"]}
    world = {"id": wid, "owner": owner, "revision": 1, "content": deepcopy(pack["world"]),
             "brief": pack["summary"], "created_at": created, "origin": origin}
    story = {"id": sid, "world_id": wid, "owner": owner, "revision": 1,
             "world_revision": 1, "world_content": deepcopy(pack["world"]),
             "content": deepcopy(pack["story"]), "brief": pack["summary"], "created_at": created,
             "origin": origin, "test_report": {"status": "pending"}}
    job = {"id": jid, "owner": owner, "kind": "catalog", "prompt": "", "story_prompt": "",
           "world_id": wid, "story_id": sid, "status": "queued", "created_at": created,
           "world_snapshot": deepcopy(world), "story_revision": 1, "checks": [], "steps": [], "error": None}
    studio.store.studio_save_batch([("worlds", world), ("stories", story), ("jobs", job)])
    studio.start(jid)
    return studio.store.jobs[jid]
