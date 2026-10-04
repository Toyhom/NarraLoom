"""Navigation helpers for the reference workspace acceptance suites."""


async def tab(page, group, section):
    await page.locator(f"#{group}-tab-{section}").click()


async def expand(locator):
    if await locator.get_attribute("open") is None:
        await locator.locator(":scope > summary").click()


async def module(page, role):
    await tab(page, "provider", "modules")
    await expand(page.locator(".engine-bindings"))
    await expand(page.locator(".module-binding").filter(has=page.get_by_label(role + " provider", exact=True)))


async def story_tools(card):
    await expand(card.locator(".story-tools"))
