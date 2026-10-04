"""Real provider/browser acceptance for generated, edited and replayed state mechanics."""

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from browser_navigation import story_tools, tab
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18091")
    parser.add_argument("--output", default="outputs/validation/states-browser")
    parser.add_argument("--resume-from", help="Reuse the creation/session of a prior failed acceptance run")
    args = parser.parse_args()
    folder = (ROOT/args.output).resolve()
    if not folder.is_relative_to(ROOT/"outputs/validation"):
        raise ValueError("Invalid report location")
    folder.mkdir(parents=True, exist_ok=False)
    previous_report = {}
    report = {"status": "running", "mode": "live_models", "errors": [], "actions": []}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context_args = {"storage_state": str((ROOT/args.resume_from)/"browser-session.local.json")} if args.resume_from else {}
        page = await browser.new_page(locale='zh-CN', viewport={"width": 1440, "height": 1000}, **context_args)
        page.on("pageerror", lambda e: report["errors"].append(str(e)))

        async def wait_job(job):
            previous = None
            for _ in range(600):
                job = await (await page.request.get(args.url+"/api/studio/jobs/"+job["id"])).json()
                status = (job["status"], len(job["steps"]))
                if status != previous:
                    print("state creation", *status, job.get("error") or "", flush=True)
                    previous = status
                if job["status"] in {"ready", "failed", "cancelled", "interrupted"}:
                    break
                await asyncio.sleep(2)
            (folder/(job["id"]+".json")).write_text(json.dumps(job, ensure_ascii=False, indent=2))
            assert job["status"] == "ready", job.get("error")
            assert any(c["name"] == "自定义状态真实模型路线" and c["status"] == "passed" for c in job["checks"])
            assert any(c["name"] == "内容与机制一致性审核" and c["status"] == "passed" for c in job["checks"])
            return job

        try:
            await page.goto(args.url)
            if args.resume_from:
                previous_report = json.loads((ROOT/args.resume_from/"report.json").read_text())
                job = {"id": previous_report["job_id"]}
            else:
                await page.get_by_role("button", name="创建我的世界", exact=True).click()
                await page.get_by_label("世界构想", exact=True).fill("星铃镇修理钟楼的温暖小故事。居民各有秘密，旅人可以观察齿轮和整理旧笔记。")
                await page.get_by_label("第一个故事（可选）").fill("从地点0开始，寻找停钟原因。额外状态玩法：记录整理推进校准进度，完成两项自主行动后开启已校准状态，不需要战斗或钱。")
                await page.get_by_label("自动设计状态玩法", exact=True).check()
                async with page.expect_response(lambda r: r.url.endswith("/api/studio/worlds") and r.request.method == "POST") as response:
                    await page.get_by_role("button", name="生成世界与第一个故事", exact=True).click()
                job = await (await response.value).json()
            await page.context.storage_state(path=str(folder/"browser-session.local.json"))
            report["job_id"] = job["id"]
            job = await wait_job(job)
            export_url = args.url+"/api/studio/stories/"+job["story_id"]+"/export"
            exported = await (await page.request.get(export_url)).json()
            pack = exported["story"]["state_rules"]
            (folder/"creator-content.local.json").write_text(json.dumps(exported, ensure_ascii=False, indent=2))
            assert pack["variables"] and pack["actions"] and pack["triggers"] and pack["tests"]
            report["generated"] = {k: len(v) for k, v in pack.items()}

            if previous_report.get("edited_job"):
                edited_job = await wait_job({"id": previous_report["edited_job"]})
            else:
                await page.reload()
                await story_tools(page.locator(f'[data-story-id="{job["story_id"]}"]'))
                await page.get_by_role("button", name="编辑故事 "+exported["story"]["title"], exact=True).click()
                await tab(page, 'editor', 'systems')
                await page.get_by_role("button", name="展开状态编辑器", exact=False).click()
                secret_index = next((i for i, v in enumerate(pack["variables"]) if v["name"] == "主持秘密验收值"), None)
                if secret_index is None:
                    await page.get_by_role("button", name="添加变量", exact=True).click()
                    secret_index = len(pack["variables"])
                block = page.locator(".state-editor details").nth(secret_index)
                await block.locator("summary").click()
                await block.get_by_label("变量名称", exact=True).fill("主持秘密验收值")
                await block.get_by_label("变量可见性", exact=True).select_option("gm")
                await block.get_by_label("初始值", exact=True).fill("37")
                await page.set_viewport_size({"width": 390, "height": 844})
                assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"), "Editor mobile overflow"
                await page.screenshot(path=str(folder/"state-editor-mobile.png"), full_page=True)
                await page.set_viewport_size({"width": 1440, "height": 1000})
                await page.screenshot(path=str(folder/"state-editor.png"), full_page=True)
                async with page.expect_response(lambda r: r.url.endswith("/api/studio/stories/"+job["story_id"]) and r.request.method == "PUT") as response:
                    await page.get_by_role("button", name="保存并自动测试", exact=True).click()
                response = await response.value
                assert response.ok, await response.text()
                edited_job = await wait_job(await response.json())
            report["edited_job"] = edited_job["id"]
            exported = await (await page.request.get(export_url)).json()
            assert exported["story"]["state_rules"]["variables"][-1]["initial"] == 37
            pack = exported["story"]["state_rules"]
            await page.reload()
            async with page.expect_response(lambda r: r.url.endswith("/api/campaigns") and r.request.method == "POST") as response:
                await page.get_by_role("button", name="开始这个故事", exact=True).click()
            campaign = await (await response.value).json()
            report["campaign"] = campaign
            root = args.url+"/api/campaigns/"+campaign["id"]+"/branches/"+campaign["branch_id"]

            async def view():
                return await (await page.request.get(root+"/view")).json()

            async def wait_action(action, refresh=False):
                for _ in range(360):
                    action = await (await page.request.get(args.url+"/api/actions/"+action["id"])).json()
                    if action["status"] in {"committed", "failed", "cancelled", "interrupted"}:
                        break
                    await asyncio.sleep(.5)
                assert action["status"] == "committed", action.get("error")
                if refresh:
                    await page.reload()
                    await tab(page, "inspector", "actions")
                version = (await view())["world_version"]
                await page.locator(f'.turn[data-version="{version}"]').wait_for(timeout=15000)
                report["actions"].append({"id": action["id"], "version": version, "effects": action["result"]["effects"]})
                print("state action", version, flush=True)
                return action

            session = await (await page.request.post(args.url+"/api/session")).json()
            headers = {"X-CSRF-Token": session["csrf_token"]}
            initial = await view()
            assert "主持秘密验收值" not in json.dumps(initial, ensure_ascii=False)
            await tab(page, "inspector", "actions")
            for i, step in enumerate(pack["tests"][0]["steps"]):
                if step["kind"] == "state_action":
                    name = next(a["name"] for a in pack["actions"] if a["id"] == step["target_id"])
                    async with page.expect_response(lambda r: r.url.endswith("/actions") and r.request.method == "POST") as response:
                        await page.locator(".custom-state-panel").get_by_role("button", name=name, exact=True).click()
                    action_response = await response.value
                    command = action_response.request.post_data_json
                    action = await wait_action(await action_response.json())
                else:
                    # State actions are exercised through visible controls; supporting navigation uses typed API.
                    current = await view()
                    mode = step["kind"] if step["kind"] in {"wait", "say"} else "act"
                    command = {"action_id": "qa_state_"+uuid.uuid4().hex[:24], "expected_world_version": current["world_version"],
                               "mode": mode, "text": f"我等待{step['seconds']}秒。" if mode == "wait" else "我执行验收路线的这一步。"}
                    if mode == "act":
                        command["selected_operation"] = {"kind": step["kind"], "target_id": step["target_id"]}
                    response = await page.request.post(root+"/actions", data=command, headers=headers)
                    assert response.status == 202, await response.text()
                    action = await wait_action(await response.json(), refresh=True)
                duplicate = await (await page.request.post(root+"/actions", data=command, headers=headers)).json()
                assert duplicate == action, "Repeated request must return the same public receipt"
            final = await view()
            values = {v["id"]: v["value"] for v in final["custom_state"]["variables"]}
            visible_assertions = 0
            for expected in pack["tests"][0]["expect"]:
                if expected["source"] == "variable" and expected["key"] in values and expected["op"] == "eq":
                    assert values[expected["key"]] == expected["value"]
                    visible_assertions += 1
            report["visible_assertions"] = visible_assertions
            assert "主持秘密验收值" not in json.dumps(final, ensure_ascii=False)
            await page.reload()
            await tab(page, 'inspector', 'actions')
            await page.locator(".custom-state-panel").wait_for()
            assert (await view())["custom_state"] == final["custom_state"]
            await page.screenshot(path=str(folder/"state-play.png"), full_page=True)
            await page.set_viewport_size({"width": 390, "height": 844})
            await page.get_by_role("button", name="角色与行囊", exact=True).click()
            assert await page.locator(".custom-state-panel").is_visible()
            assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
            await page.screenshot(path=str(folder/"state-play-mobile.png"), full_page=True)
            fork_response = await page.request.post(args.url+"/api/campaigns/"+campaign["id"]+"/branches", headers=headers,
                data={"source_branch_id": campaign["branch_id"], "world_version": 0, "title": "状态变化之前"})
            assert fork_response.ok, await fork_response.text()
            fork = await fork_response.json()
            fork_view = await (await page.request.get(args.url+"/api/campaigns/"+campaign["id"]+"/branches/"+fork["id"]+"/view")).json()
            assert fork_view["custom_state"] == initial["custom_state"]
            backup = await (await page.request.get(args.url+"/api/campaigns/"+campaign["id"]+"/backup")).body()
            context = await browser.new_context(locale='zh-CN')
            new_session = await (await context.request.post(args.url+"/api/session")).json()
            restored_response = await context.request.post(args.url+"/api/backups/restore", data=backup,
                headers={"X-CSRF-Token": new_session["csrf_token"], "Content-Type": "application/json"})
            assert restored_response.ok, await restored_response.text()
            restored = await restored_response.json()
            restored_view = await (await context.request.get(args.url+"/api/campaigns/"+restored["id"]+"/branches/"+restored["branch_id"]+"/view")).json()
            assert restored_view["custom_state"] == final["custom_state"]
            await context.close()
            report.update(status="passed", secret_projection=True, idempotent=True, branch_isolation=True,
                          backup_restore=True, mobile=True, creation_steps=len(job["steps"]), edited_steps=len(edited_job["steps"]))
            assert not report["errors"], report["errors"]
        except Exception as exc:
            report.update(status="failed", failure=str(exc))
            await page.screenshot(path=str(folder/"failure.png"), full_page=True)
            raise
        finally:
            (folder/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
