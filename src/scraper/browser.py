"""Managed Playwright browser context — single shared instance per run."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from loguru import logger
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from src.config import settings


class BrowserManager:
    """Owns the Playwright instance, browser, and a single persistent context."""

    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def start(self) -> BrowserContext:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=settings.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        self._context = await self._browser.new_context(
            locale="es-PE",
            timezone_id="America/Lima",
            accept_downloads=True,
            # Emulate a real desktop browser so the site doesn't block us
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900},
        )
        # Hide webdriver fingerprint
        await self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        logger.info("Browser context started (headless={})", settings.headless)
        return self._context

    async def new_page(self) -> Page:
        if self._context is None:
            await self.start()
        page = await self._context.new_page()  # type: ignore[union-attr]
        page.set_default_timeout(settings.timeout_ms)
        page.set_default_navigation_timeout(settings.nav_timeout_ms)
        return page

    async def stop(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        logger.info("Browser context stopped.")


@asynccontextmanager
async def managed_browser() -> AsyncGenerator[BrowserManager, None]:
    """Async context manager that guarantees cleanup."""
    mgr = BrowserManager()
    await mgr.start()
    try:
        yield mgr
    finally:
        await mgr.stop()
