import runpy
from pathlib import Path

import pytest

from roleplay_world.contracts import ActionCommand
from roleplay_world.store import Store

snapshot = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/snapshot_store.py"))["snapshot"]


@pytest.mark.parametrize("work", ["action", "creation"])
def test_snapshot_checks_raw_active_status_without_writer_or_recovery(tmp_path, template, work):
    store = Store(tmp_path)
    try:
        campaign = store.create_campaign("owner", template, "Traveler")
        if work == "action":
            store.accept(campaign["id"], campaign["main_branch"], "owner", ActionCommand(
                action_id="active", expected_world_version=0, text="Look around"))
        else:
            store.studio_save("jobs", {"id": "active", "status": "testing", "owner": "owner"})
        before = store.journal.path.read_bytes()
        with pytest.raises(RuntimeError, match="active"):
            snapshot(tmp_path)
        assert store.journal.path.read_bytes() == before
    finally:
        store.close()
    # Raw status remains active even after the writer ends, until explicit recovery.
    with pytest.raises(RuntimeError, match="active"):
        snapshot(tmp_path)


def test_snapshot_replays_idle_store_and_leaves_partial_tail_untouched(tmp_path, template):
    store = Store(tmp_path)
    try:
        store.create_campaign("owner", template, "Traveler")
        first = snapshot(tmp_path)  # The live writer's exclusive lock is still held.
        assert len(first["campaigns"]) == len(first["branches"]) == 1
    finally:
        store.close()
    assert snapshot(tmp_path) == first
    path = tmp_path / "journal.jsonl"
    raw = path.read_bytes() + b'{"unfinished"'
    path.write_bytes(raw)
    with pytest.raises(RuntimeError, match="incomplete frame"):
        snapshot(tmp_path)
    assert path.read_bytes() == raw
    assert not list(tmp_path.glob("recovery-tail-*"))
