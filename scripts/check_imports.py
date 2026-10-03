"""Migrate a pinned real SillyTavern director/card/lorebook bundle using the configured model."""

import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18091")
    parser.add_argument("--output", default="outputs/validation/imports-live")
    args = parser.parse_args()
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT / "outputs/validation"):
        raise ValueError("Output must be in project validation folder")
    folder.mkdir(parents=True, exist_ok=False)
    report = {"status": "running", "mode": "live_models", "sources": []}
    with httpx.Client(base_url=args.url, trust_env=False, timeout=20) as client:
        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        def post(path, **kwargs):
            response = client.post(path, **kwargs)
            response.raise_for_status()
            return response.json()

        def wait(job, name):
            deadline, previous = time.monotonic() + 1200, None
            while time.monotonic() < deadline:
                job = get("/api/studio/jobs/" + job["id"])
                status = (job["status"], len(job.get("steps", [])))
                if status != previous:
                    print(name, *status, job.get("error") or "", flush=True)
                    previous = status
                (folder / (name + ".json")).write_text(json.dumps(job, ensure_ascii=False, indent=2))
                if job["status"] in {"ready", "failed", "cancelled", "interrupted", "recovery_required"}:
                    break
                time.sleep(2)
            assert job["status"] == "ready", job.get("error")
            return job

        try:
            client.headers["X-CSRF-Token"] = post("/api/session")["csrf_token"]
            (folder / "session.local.json").write_text(json.dumps(dict(client.cookies)))
            report["provider"] = get("/api/status")
            assert report["provider"]["ready"]
            base = ROOT / "resources/community/world-forge/Samples/Apartment_Test_Director/Export"
            for name in ["WorldDirector_Card.json", "Apartment_NPC_Lorebook.json",
                         "Apartment_World_Lorebook.json", "Sandbox_Lorebook.json"]:
                raw = (base / name).read_bytes()
                source = post("/api/studio/imports", params={"filename": name}, content=raw)
                original = client.get("/api/studio/imports/" + source["id"] + "/original")
                assert original.content == raw
                assert source["sha256"] == hashlib.sha256(raw).hexdigest()
                report["sources"].append({"id": source["id"], "name": name, "sha256": source["sha256"]})
            iid = report["sources"][0]["id"]
            payload = {"additional_ids": [s["id"] for s in report["sources"][1:]],
                       "brief": "完整保留公寓与Priya、Theo、Nadia的人物关系和语气，创作新室友加入的日常沙盒入门故事，目标不强迫NPC答应。"}
            job = wait(post(f"/api/studio/imports/{iid}/convert", json=payload), "converted")
            assert post(f"/api/studio/imports/{iid}/convert", json=payload)["id"] == job["id"]
            exported = get("/api/studio/stories/" + job["story_id"] + "/export")
            assert len(exported["origin"]["source_data"]["sources"]) == 4
            assert all(any(name in c["name"] for c in exported["world"]["characters"])
                       for name in ["Priya", "Theo", "Nadia"])
            assert all(r["status"] != "candidate" for r in job["conversion_report"])
            (folder / "converted-story.json").write_text(json.dumps(exported, ensure_ascii=False, indent=2))
            raw = json.dumps(exported, ensure_ascii=False).encode()
            native = post("/api/studio/imports", params={"filename": "roundtrip.json"}, content=raw)
            restored = wait(post("/api/studio/imports/" + native["id"] + "/convert", json={}), "roundtrip")
            again = get("/api/studio/stories/" + restored["story_id"] + "/export")
            assert again == exported
            campaign = post("/api/campaigns", json={"story_id": restored["story_id"], "player_name": "新室友"})
            view = get(f"/api/campaigns/{campaign['id']}/branches/{campaign['branch_id']}/view")
            assert not any(c["secret"] in json.dumps(view, ensure_ascii=False) for c in exported["world"]["characters"])
            report.update(status="passed", conversion_report=job["conversion_report"], roundtrip_exact=True,
                          characters=[c["name"] for c in exported["world"]["characters"]],
                          tested_steps=[len(job["steps"]), len(restored["steps"])], campaign=campaign)
        except Exception as exc:
            report.update(status="failed", error=str(exc)[:1000])
            raise
        finally:
            (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print("IMPORT ACCEPTANCE PASSED", flush=True)


if __name__ == "__main__":
    main()
