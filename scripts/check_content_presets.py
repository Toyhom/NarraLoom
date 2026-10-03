"""Real-model acceptance for lightweight creation, content languages and native round trips."""

import argparse
import asyncio
import json
import re
import uuid
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18091")
    parser.add_argument("--output", required=True)
    parser.add_argument("--resume-from", help="Resume the saved jobs and browser identity of a previous run")
    args = parser.parse_args()
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT / "outputs/validation"):
        raise ValueError("Reports belong in outputs/validation")
    folder.mkdir(parents=True, exist_ok=False)
    previous = (ROOT / args.resume_from).resolve() if args.resume_from else None
    report = json.loads((previous / "report.json").read_text()) if previous else {"jobs": {}, "actions": [], "errors": []}
    report.pop("error", None)
    report.update(status="running", mode="live_models", resumed_from=args.resume_from)

    def save():
        (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(locale='zh-CN', viewport={"width": 1440, "height": 1000}, **(
            {"storage_state": str(previous / "session.local.json")} if previous else {}))
        page = await context.new_page()
        page.on("pageerror", lambda e: report["errors"].append(str(e)))
        csrf = None

        async def call(path, body=None, method=None, raw=False):
            response = await context.request.fetch(args.url + path, method=method or ("POST" if body is not None else "GET"),
                data=body, headers={"X-CSRF-Token": csrf or "", "Content-Type": "application/octet-stream" if raw else "application/json"})
            assert response.ok, (response.status, await response.text())
            return await response.json()

        async def wait_job(job):
            last = None
            for _ in range(600):
                job = await call("/api/studio/jobs/" + job["id"])
                status = (job["status"], len(job["steps"]))
                if status != last:
                    print(job["id"], *status, job.get("error") or "", flush=True)
                    last = status
                (folder / (job["id"] + ".json")).write_text(json.dumps(job, ensure_ascii=False, indent=2))
                if job["status"] in {"ready", "failed", "cancelled", "interrupted", "recovery_required"}:
                    break
                await asyncio.sleep(2)
            assert job["status"] == "ready", job.get("error") or job["status"]
            return job

        async def create(label, path, payload):
            if label not in report["jobs"]:
                report["jobs"][label] = (await call(path, payload))["id"]
                save()
            return await wait_job({"id": report["jobs"][label]})

        async def export(job, label):
            content = await call("/api/studio/stories/" + job["story_id"] + "/export")
            (folder / (label + ".local.json")).write_text(json.dumps(content, ensure_ascii=False, indent=2))
            return content

        try:
            await page.goto(args.url)
            await page.get_by_role("button", name="创建我的世界", exact=True).wait_for()
            csrf = (await call("/api/session", {}, "POST"))["csrf_token"]
            await context.storage_state(path=str(folder / "session.local.json"))
            if "english_scene" in report["jobs"]:
                await page.get_by_role("button", name="创建我的世界", exact=True).click()
                await page.get_by_label("创作规模", exact=True).select_option("scene")
                await page.get_by_role("dialog").get_by_label("内容语言", exact=True).select_option("en")
                await page.set_viewport_size({"width": 390, "height": 844})
                box = await page.get_by_label("自动设计主动世界", exact=True).bounding_box()
                assert box and box["width"] <= 24 and box["height"] <= 24
                assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                await page.screenshot(path=str(folder / "creation-mobile.png"))
                await page.get_by_role("button", name="关闭创建窗口", exact=True).click()
                await page.set_viewport_size({"width": 1440, "height": 1000})
            if "english_scene" not in report["jobs"]:
                await page.get_by_role("button", name="创建我的世界", exact=True).click()
                await page.get_by_label("创作规模", exact=True).select_option("scene")
                await page.get_by_role("dialog").get_by_label("内容语言", exact=True).select_option("en")
                await page.get_by_label("世界构想", exact=True).fill("雨天的一间社区画室，玩家与一位友好的画师交谈。风格温暖自然，不需要调查、战斗、装备或目标。人物名字使用英语。")
                await page.get_by_label("第一个故事（可选）").fill("在画室里自由交流对雨天的印象，玩家自行决定如何回应。")
                await page.set_viewport_size({"width": 390, "height": 844})
                assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                box = await page.get_by_label("自动设计主动世界", exact=True).bounding_box()
                assert box and box["width"] <= 24 and box["height"] <= 24
                await page.screenshot(path=str(folder / "creation-mobile.png"))
                await page.set_viewport_size({"width": 1440, "height": 1000})
                async with page.expect_response(lambda r: r.url.endswith("/api/studio/worlds") and r.request.method == "POST") as response:
                    await page.get_by_role("button", name="生成世界与第一个故事", exact=True).click()
                report["jobs"]["english_scene"] = (await (await response.value).json())["id"]
                save()
            english = await wait_job({"id": report["jobs"]["english_scene"]})
            content = await export(english, "english-scene")
            assert content["world"]["content_language"] == content["story"]["content_language"] == "en"
            assert len(content["world"]["locations"]) == len(content["world"]["characters"]) == 1
            assert not content["story"]["clues"] and not content["story"]["challenges"]
            assert not content["story"]["starting_item"] and not content["story"]["pressure_name"]
            assert not re.search(r"[\u4e00-\u9fff]", content["story"]["opening"])
            await page.reload()
            await page.locator(".studio-world-card").filter(has=page.get_by_role("heading", name=content["world"]["title"], exact=True)).first.click()
            card = page.locator(f'[data-story-id="{english["story_id"]}"]')
            async with page.expect_response(lambda r: r.url.endswith("/api/campaigns") and r.request.method == "POST") as response:
                await card.get_by_role("button", name="开始这个故事", exact=True).click()
            campaign = await (await response.value).json()
            report["campaign"] = campaign
            base = f"/api/campaigns/{campaign['id']}/branches/{campaign['branch_id']}"
            before = await call(base + "/view")
            assert not before["resources"] and not before["inventory"] and not before["visible_clocks"] and not before["quests"]
            assert await page.locator(".resources, .route-list, .empty-inventory, .clock-meter, .world-map").count() == 0
            for text, mode in [("I take a moment to look around the room.", "act"), ("你好，今天过得怎么样？", "say")]:
                view = await call(base + "/view")
                command = {"action_id": "lang_" + uuid.uuid4().hex, "expected_world_version": view["world_version"], "text": text, "mode": mode}
                action = await call(base + "/actions", command)
                for _ in range(360):
                    action = await call("/api/actions/" + action["id"])
                    if action["status"] in {"committed", "failed", "interrupted"}:
                        break
                    await asyncio.sleep(.5)
                assert action["status"] == "committed", action.get("error")
                assert not re.search(r"[\u4e00-\u9fff]", " ".join(s["text"] for s in action["result"]["segments"]))
                assert (await call(base + "/actions", command))["result"]["id"] == action["result"]["id"]
                report["actions"].append(action)
                save()
            after = await call(base + "/view")
            await page.reload()
            await page.locator('.turn[data-version="2"]').wait_for()
            assert await call(base + "/view") == after
            await page.screenshot(path=str(folder / "scene-desktop.png"), full_page=True)
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
            await page.screenshot(path=str(folder / "scene-mobile.png"), full_page=True)
            await page.set_viewport_size({"width": 1440, "height": 1000})
            second = await create("japanese_story", f"/api/studio/worlds/{english['world_id']}/stories",
                {"prompt": "A quiet conversation the next morning, independent of the rainy afternoon.", "content_language": "ja", "creation_preset": "scene"})
            second_content = await export(second, "japanese-story")
            assert second_content["world"] == content["world"]
            assert second_content["story"]["content_language"] == "ja"
            assert re.search(r"[\u3040-\u30ff]", second_content["story"]["opening"])
            assert await call(base + "/view") == after
            chinese = await create("chinese_scene", "/api/studio/worlds", {
                "prompt": "河边茶室里只有一位悠闲的店主，玩家在这里等雨停，自由聊茶与旅行。", "content_language": "auto", "creation_preset": "scene"})
            chinese_content = await export(chinese, "chinese-scene")
            assert chinese_content["world"]["content_language"].startswith("zh")
            short = await create("short_story", "/api/studio/worlds", {
                "prompt": "A small community radio station and its two volunteers.",
                "story_prompt": "Investigate a mistimed broadcast; restore the schedule after reading the evidence.",
                "content_language": "en", "creation_preset": "story"})
            short_content = await export(short, "short-story")
            assert len(short_content["world"]["locations"]) == 3 and len(short_content["world"]["characters"]) == 2
            assert len(short_content["story"]["clues"]) == 2 and len(short_content["story"]["challenges"]) == 2
            source = await call("/api/studio/imports?filename=english-scene.json", json.dumps(content).encode(), raw=True)
            native = await create("native_restore", f"/api/studio/imports/{source['id']}/convert", {"content_language": "zh-CN"})
            restored = await export(native, "native-restored")
            assert restored["world"] == content["world"] and restored["story"] == content["story"]
            # Synthetic multilingual community-format fixture; no third-party authoring is silently modified.
            card = {"spec": "chara_card_v2", "spec_version": "2.0", "data": {
                "name": "花", "description": "雨の日、小さな花屋で働く花。落ち着いた性格で、植物について話すのが好き。",
                "scenario": "一つの花屋で自由に会話する。冒険や戦闘はない。", "first_mes": "こんにちは。雨が止むまで、ここで休んでいきませんか。"}}
            source = await call("/api/studio/imports?filename=hana.json", json.dumps(card, ensure_ascii=False).encode(), raw=True)
            imported = await create("source_language", f"/api/studio/imports/{source['id']}/convert", {
                "brief": "Preserve this simple conversation in one room. Do not add quests, equipment or a countdown.", "content_language": "auto"})
            converted = await export(imported, "japanese-card")
            assert converted["world"]["content_language"] == converted["story"]["content_language"] == "ja"
            assert len(converted["world"]["locations"]) == 1
            assert re.search(r"[\u3040-\u30ff]", converted["story"]["opening"])
            state_scene = await create("state_scene", "/api/studio/worlds", {
                "prompt": "A single-room radio workshop with one researcher. The player can adjust a signal without any combat or purchases.",
                "story_prompt": "Optional calibration state: two simple controls increase alignment, then a one-time trigger marks calibration complete. No required quests, gear or clock.",
                "content_language": "en", "creation_preset": "scene", "custom_states": True})
            state_content = await export(state_scene, "state-scene")
            assert state_content["story"]["state_rules"]["tests"]
            assert not state_content["story"]["challenges"] and not state_content["story"]["pressure_name"]
            assert any(c["name"] == "自定义状态真实模型路线" and c["status"] == "passed" for c in state_scene["checks"])
            assert any(c["name"] == "内容与机制一致性审核" and c["status"] == "passed" for c in state_scene["checks"])
            report["usage"] = await call("/api/settings/usage")
            assert not report["errors"], report["errors"]
            report["status"] = "passed"
        except Exception as exc:
            report.update(status="failed", error=str(exc))
            await page.screenshot(path=str(folder / "failure.png"), full_page=True)
            raise
        finally:
            save()
            await browser.close()
    print("CONTENT_PRESETS_PASSED", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
