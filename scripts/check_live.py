"""Real model API acceptance. Does not load a model or submit another GPU job."""

import argparse
import json
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18090")
    parser.add_argument("--output", default="outputs/validation/live")
    args = parser.parse_args()
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT):
        raise ValueError("Output must stay inside the project")
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    with httpx.Client(base_url=args.url, trust_env=False, timeout=15) as client:
        csrf = client.post("/api/session").json()["csrf_token"]
        client.headers["X-CSRF-Token"] = csrf
        health = client.get("/api/status").json()
        assert health["ready"], health
        c = client.post("/api/campaigns", json={"player_name": "验收旅人"}).json()
        base = f'/api/campaigns/{c["id"]}/branches/{c["branch_id"]}'
        (folder / "campaign.json").write_text(json.dumps(c, indent=2))

        def turn(text, mode="act"):
            view = client.get(base + "/view").json()
            command = {"action_id": "live_" + uuid.uuid4().hex[:24],
                       "expected_world_version": view["world_version"], "text": text, "mode": mode}
            start = time.monotonic()
            r = client.post(base + "/actions", json=command)
            r.raise_for_status()
            while time.monotonic() - start < 185:
                a = client.get("/api/actions/" + command["action_id"]).json()
                if a["status"] in {"committed", "failed", "cancelled", "interrupted"}:
                    break
                time.sleep(.5)
            after = client.get(base + "/view").json()
            result = {"text": text, "elapsed_s": round(time.monotonic() - start, 3), "action": a,
                      "view": after}
            results.append(result)
            (folder / "turns.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
            print(json.dumps({"turn": len(results), "status": a["status"], "elapsed_s": result["elapsed_s"],
                              "location": after["location"]["id"], "error": a.get("error")}, ensure_ascii=False), flush=True)
            assert a["status"] == "committed", a
            duplicate = client.post(base + "/actions", json=command).json()
            assert duplicate["result"]["id"] == a["result"]["id"]
            return after

        turn("我向船长打招呼，问她这艘船出了什么问题。", "say")
        view = turn("我把自己背包里的修理工具交给岚船长，帮助她修船。")
        assert not view["inventory"], "Real NPC did not accept the offered tools"
        view = turn("我去雾灯酒馆打听其它离港方法。")
        assert view["location"]["id"] == "loc_tavern"
        assert all(s.get("speaker_id") != "npc_captain" for s in results[-1]["action"]["result"]["segments"])
        turn("我问酒馆老板：除了坐船，这里还有别的离港路线吗？", "say")
        view = turn("我回到旧码头。")
        assert view["location"]["id"] == "loc_dock"
        turn("我使用船长手里的工具协助修补船体。")
        view = turn("我留在码头等待三十分钟。", "wait")
        assert next(x for x in view["visible_clocks"] if x["id"] == "clock_tide")["value"] == 4
        view = turn("我前往旧灯塔。")
        assert view["location"]["id"] == "loc_lighthouse"
        view = turn("我仔细查看灯塔背后的山脊小路，确认能否从那里离开。")
        assert any(f["id"] == "fact_ridge_path" for f in view["known_facts"])
        view = turn("我选择沿着已经发现的山脊小路步行离开雾港。")
        assert view["quests"][0]["status"] == "completed"
        fork = client.post(f'/api/campaigns/{c["id"]}/branches',
                           json={"source_branch_id": c["branch_id"], "world_version": 1, "title": "交出工具之前"}).json()
        fview = client.get(f'/api/campaigns/{c["id"]}/branches/{fork["id"]}/view').json()
        assert len(fview["inventory"]) == 1 and len(fview["history"]) == 1
        transcript = client.get(base + "/export").json()
        assert transcript["scope"] == "player_transcript"
        report = {"status": "passed", "mode": "live", "health": health, "turns": len(results),
                  "idempotency": "passed", "fork_before_transfer": "passed", "export": "passed",
                  "elapsed_s": [r["elapsed_s"] for r in results]}
        (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
