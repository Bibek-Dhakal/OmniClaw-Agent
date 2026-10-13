"""Controlled headless browser automation for apps without clean APIs."""

import asyncio
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from playwright.async_api import Browser, Page, Playwright, async_playwright

from omniclaw.config import Settings
from omniclaw.memory import R2Store
from omniclaw.tools import Tool, ToolContext

RISKY_ACTION = re.compile(
    r"send|post|like|swipe|connect|submit|follow|apply|message|pass|nope", re.IGNORECASE
)
MAX_SNAPSHOT_CHARS = 6000
NAV_TIMEOUT_MS = 30000
ACTION_TIMEOUT_MS = 10000


def matching_domain(url: str, allowed: list[str]) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    for domain in allowed:
        if host == domain or host.endswith("." + domain):
            return domain
    return None


class BrowserManager:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._allowed = settings.browser_allowed_domain_list
        self._state_dir = Path(settings.browser_state_dir)
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._pages: dict[str, Page] = {}
        self._active: str | None = None
        self._lock = asyncio.Lock()
        self.last_typed: str = ""

    @property
    def url(self) -> str:
        page = self._pages.get(self._active or "")
        return page.url if page else ""

    def _active_page(self) -> Page:
        page = self._pages.get(self._active or "")
        if page is None or page.is_closed():
            raise RuntimeError("No page is open. Call browser_goto first.")
        return page

    async def _page_for(self, domain: str) -> Page:
        async with self._lock:
            page = self._pages.get(domain)
            if page is not None and not page.is_closed():
                return page
            if self._browser is None:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=self._s.browser_headless
                )
            state = self._state_dir / f"{domain}.json"
            context = await self._browser.new_context(
                storage_state=str(state) if state.exists() else None
            )
            page = await context.new_page()
            self._pages[domain] = page
            return page

    async def goto(self, url: str) -> dict[str, Any]:
        domain = matching_domain(url, self._allowed)
        if domain is None:
            raise PermissionError(f"{url} is not in BROWSER_ALLOWED_DOMAINS")
        page = await self._page_for(domain)
        await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        if matching_domain(page.url, self._allowed) != domain:
            blocked = page.url
            await page.goto("about:blank")
            raise PermissionError(f"Redirected outside the allowlist: {blocked}")
        self._active = domain
        return await self.snapshot()

    async def snapshot(self) -> dict[str, Any]:
        page = self._active_page()
        body = await page.locator("body").aria_snapshot()
        return {"url": page.url, "title": await page.title(), "snapshot": body[:MAX_SNAPSHOT_CHARS]}

    async def click(self, selector: str) -> dict[str, Any]:
        page = self._active_page()
        await page.click(selector, timeout=ACTION_TIMEOUT_MS)
        await page.wait_for_timeout(800)
        return await self.snapshot()

    async def type(self, selector: str, text: str, submit: bool) -> dict[str, Any]:
        page = self._active_page()
        await page.fill(selector, text, timeout=ACTION_TIMEOUT_MS)
        self.last_typed = text
        if submit:
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(800)
        return await self.snapshot()

    async def screenshot(self) -> bytes:
        return await self._active_page().screenshot(type="png")

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()


async def interactive_login(settings: Settings, domain: str) -> None:
    """Open a visible browser, let the owner log in, then save the session."""
    domain = domain.lower()
    if domain not in settings.browser_allowed_domain_list:
        raise SystemExit(f"{domain} is not in BROWSER_ALLOWED_DOMAINS")
    state_dir = Path(settings.browser_state_dir)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(f"https://{domain}")
        await asyncio.to_thread(
            input, "Log in in the opened window, then press Enter here to save the session... "
        )
        state_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
        await context.storage_state(path=str(state_dir / f"{domain}.json"))
        await browser.close()
    print(f"Saved session for {domain} to {state_dir}")


def build_browser_tools(manager: BrowserManager, r2: R2Store) -> list[Tool]:
    async def goto(args: dict[str, Any], ctx: ToolContext) -> Any:
        return await manager.goto(args["url"])

    async def snapshot(args: dict[str, Any], ctx: ToolContext) -> Any:
        return await manager.snapshot()

    async def click(args: dict[str, Any], ctx: ToolContext) -> Any:
        return await manager.click(args["selector"])

    async def type_text(args: dict[str, Any], ctx: ToolContext) -> Any:
        return await manager.type(args["selector"], args["text"], bool(args.get("submit", False)))

    async def screenshot(args: dict[str, Any], ctx: ToolContext) -> Any:
        if not r2.enabled:
            raise RuntimeError("R2 is not configured, cannot store screenshots.")
        key = f"screenshots/{uuid4().hex}.png"
        await r2.put(key, await manager.screenshot(), "image/png")
        return {"r2_key": key}

    def click_needs_approval(args: dict[str, Any]) -> bool:
        return bool(RISKY_ACTION.search(str(args.get("selector", ""))))

    def click_description(args: dict[str, Any]) -> str:
        return (
            f"browser_click {args.get('selector')} on {manager.url}\n"
            f"Pending typed text: {manager.last_typed!r}"
        )

    def type_needs_approval(args: dict[str, Any]) -> bool:
        return bool(args.get("submit", False))

    def type_description(args: dict[str, Any]) -> str:
        return (
            f"Type and submit on {manager.url} into {args.get('selector')}:\n{args.get('text')!r}"
        )

    return [
        Tool(
            name="browser_goto",
            description="Open a URL in the headless browser (allowlisted domains only).",
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            handler=goto,
        ),
        Tool(
            name="browser_snapshot",
            description="Return the accessibility snapshot of the current page.",
            parameters={"type": "object", "properties": {}},
            handler=snapshot,
        ),
        Tool(
            name="browser_click",
            description=(
                "Click an element using a Playwright selector, for example "
                'role=button[name="Send"] or text=Messages.'
            ),
            parameters={
                "type": "object",
                "properties": {"selector": {"type": "string"}},
                "required": ["selector"],
            },
            handler=click,
            needs_approval=click_needs_approval,
            describe=click_description,
        ),
        Tool(
            name="browser_type",
            description="Fill text into an element. Set submit=true to press Enter afterwards.",
            parameters={
                "type": "object",
                "properties": {
                    "selector": {"type": "string"},
                    "text": {"type": "string"},
                    "submit": {"type": "boolean"},
                },
                "required": ["selector", "text"],
            },
            handler=type_text,
            needs_approval=type_needs_approval,
            describe=type_description,
        ),
        Tool(
            name="browser_screenshot",
            description="Take a screenshot of the current page and store it in R2.",
            parameters={"type": "object", "properties": {}},
            handler=screenshot,
        ),
    ]
