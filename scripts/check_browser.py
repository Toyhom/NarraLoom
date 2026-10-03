"""Exercise the actual browser, model-backed turns, cancellation and mobile layout."""

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:18090")
    p.add_argument("--output", default="outputs/validation/browser")
    p.add_argument("--visual-only", action="store_true")
    args = p.parse_args()
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT):
        raise ValueError("Output must stay in the project")
    folder.mkdir(parents=True, exist_ok=True)
    errors = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN", accept_downloads=True)
        page = await context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto(args.url)
        await page.get_by_role("button", name="体验内置雾港故事").wait_for()
        await page.screenshot(path=str(folder / "library-desktop.png"), full_page=True)
        await page.get_by_role("button", name="体验内置雾港故事").click()
        await page.get_by_label("你的行动").wait_for()
        await page.screenshot(path=str(folder / "opening-desktop.png"))

        async def view():
            return await page.evaluate("""async () => {
                const x = JSON.parse(localStorage.getItem('rpw-active'));
                return (await fetch(`/api/campaigns/${x.cid}/branches/${x.bid}/view`)).json();
            }""")

        if not args.visual_only:
            await page.get_by_label("你的行动").fill("我把背包里的修理工具交给岚船长，帮助她修船。")
            await page.get_by_role("button", name="继续故事").click()
            await page.locator('.turn[data-version="1"]').wait_for(timeout=185000)
            v = await view()
            assert v["world_version"] == 1 and not v["inventory"], v
            await page.screenshot(path=str(folder / "transfer-desktop.png"))
            await page.get_by_label("你的行动").fill("我问船长能否详细讲讲她以前的航海经历。")
            await page.get_by_role("button", name="继续故事").click()
            # Skip Playwright's animation-stability delay: the real model can commit
            # while smooth scrolling is still running. Backend tests cover late cancel.
            await page.get_by_role("button", name="取消行动").wait_for()
            await page.wait_for_function("!document.querySelector('.stop-button')?.disabled")
            await page.get_by_role("button", name="取消行动").click(force=True, timeout=10000)
            await page.get_by_text("行动已取消，世界状态保持原样。").wait_for()
            assert (await view())["world_version"] == 1
            await page.get_by_label("你的行动").fill("我去雾灯酒馆打听其它离港方法。")
            await page.get_by_role("button", name="继续故事").click()
            await page.locator('.turn[data-version="2"]').wait_for(timeout=185000)
            assert (await view())["location"]["id"] == "loc_tavern"
            await page.reload()
            await page.locator('.turn[data-version="2"]').wait_for()
            assert (await view())["location"]["id"] == "loc_tavern"
            await page.get_by_role("button", name="从第1幕创建分支").click()
            await page.get_by_label("给这条故事起个名字").fill("留在码头的另一条路")
            await page.get_by_role("button", name="创建故事分支").click()
            await page.wait_for_function("document.querySelector('.branch-select select')?.selectedOptions[0]?.textContent.includes('留在码头')")
            v = await view()
            assert v["location"]["id"] == "loc_dock" and v["world_version"] == 1
            async with page.expect_download() as info:
                await page.get_by_label("导出冒险手记").click()
            download = await info.value
            await download.save_as(str(folder / "player-export.json"))
            exported = json.loads((folder / "player-export.json").read_text())
            assert exported["scope"] == "player_transcript"
            assert "warehouse_to_ridge" not in json.dumps(exported)

        await page.set_viewport_size({"width": 390, "height": 844})
        await page.screenshot(path=str(folder / "adventure-mobile.png"))
        assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        await page.get_by_role("button", name="角色与行囊").click()
        await page.screenshot(path=str(folder / "inventory-mobile.png"))
        await page.get_by_label("关闭角色面板").click()
        assert not errors, errors
        report = {"status": "passed", "mode": "visual_only" if args.visual_only else "live_models",
                  "page_errors": errors, "mobile_overflow": False,
                  "checked": ["library", "opening", "mobile_layout"] if args.visual_only else
                  ["real_transfer", "cancel_before_commit", "immediate_replacement", "refresh_restore",
                   "fork", "player_export", "mobile_layout"]}
        (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False), flush=True)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
