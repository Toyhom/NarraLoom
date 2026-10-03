import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from roleplay_world.contracts import ActionCommand, DomainError
from roleplay_world.journal import Journal, digest
from roleplay_world.store import Store


def test_journal_detects_corruption_and_recovers_tail(tmp_path):
    root = tmp_path / "log"
    journal = Journal(root)
    journal.append({"ok": 1})
    journal.close()
    with (root / "journal.jsonl").open("ab") as f:
        f.write(b'{"unfinished":')
    recovered = Journal(root)
    assert len(recovered.records) == 1
    assert len(list(root.glob("recovery-tail-*"))) == 1
    recovered.append({"ok": 2})
    recovered.close()
    content = (root / "journal.jsonl").read_text().replace('"ok":1', '"ok":9')
    (root / "journal.jsonl").write_text(content)
    with pytest.raises(RuntimeError, match="Corrupt journal"):
        Journal(root)
    assert (root / "journal.jsonl").read_text() == content


def test_second_writer_and_wrong_node_refused(tmp_path):
    journal = Journal(tmp_path)
    with pytest.raises(OSError):
        Journal(tmp_path)
    journal.close()
    (tmp_path / "writer-node.json").write_text(json.dumps({"node": "another-node"}))
    with pytest.raises(RuntimeError, match="another host"):
        Journal(tmp_path)


def test_subprocess_exit_preserves_completed_frame(tmp_path):
    code = "from pathlib import Path; from roleplay_world.journal import Journal; import os,sys; j=Journal(Path(sys.argv[1])); j.append({'committed':True}); os._exit(0)"
    # pytest's pythonpath option does not propagate to a new interpreter.
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")
           + os.pathsep + os.environ.get("PYTHONPATH", "")}
    subprocess.run([sys.executable, "-c", code, str(tmp_path)], check=True, env=env)
    recovered = Journal(tmp_path)
    assert recovered.records[-1]["body"] == {"committed": True}
    recovered.close()


def test_idempotency_restart_branch_and_owner(tmp_path, template):
    store = Store(tmp_path)
    c = store.create_campaign("alice", template, "旅人")
    cid, bid = c["id"], c["main_branch"]
    command = ActionCommand(action_id="test1", expected_world_version=0, text="等待")
    a, fresh = store.accept(cid, bid, "alice", command)
    assert fresh
    _, fresh = store.accept(cid, bid, "alice", command)
    assert not fresh
    with pytest.raises(DomainError):
        store.accept(cid, bid, "alice", command.model_copy(update={"text": "换一个请求"}))
    with pytest.raises(DomainError):
        store.action("test1", "mallory")
    event = {"event_id": "time1", "type": "time.advanced", "payload": {"before_s": 0, "after_s": 60}}
    store.commit(a["id"], [event], [{"kind": "narration", "text": "时间流逝"}], [], [], None)
    expected = digest(store.branches[bid]["state"])
    with pytest.raises(DomainError):
        store.commit(a["id"], [event], [], [], [], None)
    b = store.fork(cid, bid, "alice", 0, "另一个选择")
    assert b["state"]["game_time_s"] == 0
    assert b["commits"] == []
    assert store.branches[bid]["state"]["game_time_s"] == 60
    store.close()
    restored = Store(tmp_path)
    assert digest(restored.branches[bid]["state"]) == expected
    assert restored.actions["test1"]["status"] == "committed"
    _, fresh = restored.accept(cid, bid, "alice", command)
    assert not fresh
    restored.close()


def test_uncertain_fsync_stops_writes_and_recovers_original_commit(tmp_path, template, monkeypatch):
    store = Store(tmp_path)
    c = store.create_campaign("alice", template, "旅人")
    command = ActionCommand(action_id="uncertain", expected_world_version=0, text="等待")
    store.accept(c["id"], c["main_branch"], "alice", command)
    original = os.fsync

    def fail(fd):
        if fd == store.journal.fd:
            raise OSError("injected fsync uncertainty")
        return original(fd)

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(DomainError, match="待确认"):
        store.commit("uncertain", [], [], [], [], None)
    assert store.action("uncertain", "alice")["status"] == "recovery_required"
    with pytest.raises(DomainError, match="恢复"):
        store.create_campaign("alice", template, "另一位旅人")
    store.close()
    monkeypatch.setattr(os, "fsync", original)
    restored = Store(tmp_path)
    assert restored.action("uncertain", "alice")["status"] == "committed"
    assert restored.branches[c["main_branch"]]["state"]["version"] == 1
    assert restored.accept(c["id"], c["main_branch"], "alice", command)[1] is False
    restored.close()
