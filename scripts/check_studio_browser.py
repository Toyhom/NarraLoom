"""Browser acceptance through real creation forms, live testing, edits and gameplay."""

import argparse
import asyncio
import json
from pathlib import Path

from browser_navigation import story_tools, tab
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:18090")
    p.add_argument("--output", default="outputs/validation/studio-browser")
    args = p.parse_args()
    folder = (ROOT / args.output).resolve()
    assert folder.is_relative_to(ROOT)
    folder.mkdir(parents=True, exist_ok=True)
    errors = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1000}, locale="zh-CN", accept_downloads=True
        )
        page = await context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto(args.url)
        await page.get_by_role("button", name="创建我的世界").wait_for()
        color = await page.evaluate("getComputedStyle(document.body).backgroundColor")
        assert color == "rgb(248, 248, 243)", color
        await page.screenshot(path=str(folder / "library-light.png"), full_page=True)
        await page.get_by_role("button", name="创建我的世界").click()
        await page.get_by_label("世界构想", exact=True).fill(
            "一个会移动的森林小镇，图书馆长、植物学家与巡林员住在巨树之间，居民依靠信件交流。"
        )
        await page.get_by_label("第一个故事（可选）").fill(
            "我扮演刚来的绘图师，调查树屋地图出现的错误，通过线索找到小镇的新方向。"
        )
        async with page.expect_response(
            lambda r: r.url.endswith("/api/studio/worlds") and r.request.method == "POST"
        ) as response_info:
            await page.get_by_role("button", name="生成世界与第一个故事", exact=True).click()
        response = await response_info.value
        assert response.status == 202, await response.text()
        job = await response.json()
        await page.get_by_role("button", name="取消任务", exact=True).click()
        await page.get_by_text("任务已取消", exact=True).wait_for()
        await page.get_by_role("button", name="继续任务", exact=True).click()
        await page.reload()

        async def wait_job(jid):
            last = None
            for _ in range(600):
                value = await page.evaluate("async id => (await fetch(`/api/studio/jobs/${id}`)).json()", jid)
                status = (value["status"], len(value.get("steps", [])))
                if status != last:
                    print("BROWSER_CREATION", *status, value.get("error") or "", flush=True)
                    last = status
                (folder / (jid + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2))
                if value["status"] in ["ready", "failed", "cancelled", "interrupted"]:
                    assert value["status"] == "ready", value
                    return value
                await asyncio.sleep(2)
            raise TimeoutError("Creation timed out")

        job = await wait_job(job["id"])
        card = page.locator(f'[data-story-id="{job["story_id"]}"]')
        await card.get_by_role("button", name="开始这个故事").wait_for()
        await page.screenshot(path=str(folder / "generated-world.png"), full_page=True)
        await page.get_by_role("button", name="编辑世界", exact=True).click()
        field = page.get_by_label("世界名称", exact=True)
        title = await field.input_value()
        await field.fill(title + "·新篇")
        await tab(page, 'editor', 'locations')
        places = page.locator(".editor-block").filter(has=page.locator(".checkboxes"))
        first_place = places.nth(0)
        third_place = places.nth(2)
        await first_place.locator("summary").click()
        await third_place.locator("summary").click()
        # A route is bidirectional in the engine: edit either end and both controls agree.
        first_to_third = first_place.get_by_role("checkbox").nth(1)
        third_to_first = third_place.get_by_role("checkbox").nth(0)
        await first_to_third.check()
        assert await third_to_first.is_checked()
        await third_to_first.uncheck()
        assert not await first_to_third.is_checked()
        await first_to_third.check()
        await page.get_by_role("button", name="保存世界新版本", exact=True).click()
        await page.get_by_role("heading", name=title + "·新篇", level=2, exact=True).wait_for()
        await page.get_by_role("button", name="新建故事", exact=True).click()
        await page.get_by_label("故事构想", exact=True).fill(
            "小镇举行夜间的换书节，一封没有署名的信带来旧朋友的请求。设计不同于地图调查的新故事。"
        )
        async with page.expect_response(
            lambda r: r.url.endswith("/stories") and r.request.method == "POST"
        ) as response_info:
            await page.get_by_role("button", name="生成新故事", exact=True).click()
        second = await (await response_info.value).json()
        second = await wait_job(second["id"])
        await page.wait_for_function('document.querySelectorAll(".studio-story-card").length===2')
        await page.screenshot(path=str(folder / "two-stories.png"), full_page=True)
        card = page.locator(f'[data-story-id="{job["story_id"]}"]')
        await story_tools(card)
        await card.get_by_role("button", name="编辑故事", exact=False).click()
        await page.get_by_label("故事名称", exact=True).fill("树影里的新方向")
        await tab(page, 'editor', 'outline')
        await page.get_by_label("第 1 幕", exact=True).fill(
            "抵达小镇后听取居民的不同意见，玩家自行决定先调查哪里。"
        )
        await page.screenshot(path=str(folder / "story-editor.png"), full_page=True)
        async with page.expect_response(
            lambda r: "/api/studio/stories/" in r.url and r.request.method == "PUT"
        ) as response_info:
            await page.get_by_role("button", name="保存并自动测试", exact=True).click()
        edited = await (await response_info.value).json()
        await wait_job(edited["id"])
        card = page.locator(f'[data-story-id="{job["story_id"]}"]')
        await card.locator(".quality-report summary").click()
        await card.get_by_text("真实模型端到端", exact=False).wait_for()
        await story_tools(card)
        async with page.expect_download() as downloaded:
            await card.get_by_role("link", name="导出故事", exact=False).click()
        download = await downloaded.value
        await download.save_as(str(folder / "creator-story.json"))
        exported = json.loads((folder / "creator-story.json").read_text())
        assert exported["scope"] == "creator_story" and exported["story"]["title"] == "树影里的新方向"
        await page.get_by_label("冒险角色名称").fill("浏览器绘图师")
        await card.get_by_role("button", name="开始这个故事", exact=True).click()
        await page.get_by_label("你的行动").wait_for()

        async def view():
            return await page.evaluate(
                """async()=>{const x=JSON.parse(localStorage.getItem('rpw-active'));return (await fetch(`/api/campaigns/${x.cid}/branches/${x.bid}/view`)).json();}"""
            )

        v = await view()
        assert v["player_name"] == "浏览器绘图师" and v["title"] == "树影里的新方向"
        dest = v["exits"][0]
        await page.get_by_label("你的行动").fill(f"我去{dest['name']}打听这里的消息。")
        await page.get_by_role("button", name="继续故事").click()
        await page.locator('.turn[data-version="1"]').wait_for(timeout=185000)
        assert (await view())["location"]["id"] == dest["id"]
        await page.get_by_label("你的行动").fill("我仔细观察周围的环境。")
        await page.get_by_role("button", name="继续故事").click()
        await page.get_by_role("button", name="取消行动").wait_for()
        await page.wait_for_function("!document.querySelector('.stop-button')?.disabled")
        await page.get_by_role("button", name="取消行动").click(force=True)
        await page.get_by_text("行动已取消，世界状态保持原样。").wait_for()
        assert (await view())["world_version"] == 1
        await page.reload()
        await page.locator('.turn[data-version="1"]').wait_for()
        await page.screenshot(path=str(folder / "adventure-light.png"))
        await page.get_by_role("button", name="从第1幕创建分支").click()
        await page.get_by_label("给这条故事起个名字").fill("另一种路线")
        await page.get_by_role("button", name="创建故事分支").click()
        await page.wait_for_function(
            "document.querySelector('.branch-select select')?.selectedOptions[0]?.textContent.includes('另一种路线')"
        )
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.screenshot(path=str(folder / "adventure-mobile-light.png"))
        assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        await page.get_by_role("button", name="角色与行囊").click()
        await page.screenshot(path=str(folder / "inventory-mobile-light.png"))
        await page.get_by_label("关闭角色面板").click()
        await page.get_by_role("button", name="返回世界库").click()
        await page.get_by_role("button", name="创建我的世界").wait_for()
        await page.screenshot(path=str(folder / "studio-mobile-light.png"), full_page=True)
        assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        assert not errors, errors
        report = {
            "status": "passed",
            "mode": "live_models",
            "page_errors": errors,
            "checks": [
                "light_theme",
                "world_creation",
                "creation_cancel_and_resume",
                "reload_during_job",
                "automatic_real_playtest",
                "world_edit",
                "bidirectional_map_edit",
                "second_story",
                "story_edit_and_retest",
                "creator_export",
                "start_generated_story",
                "compound_action",
                "cancel",
                "reload_save",
                "fork",
                "mobile_studio",
                "mobile_adventure",
            ],
        }
        (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report), flush=True)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
