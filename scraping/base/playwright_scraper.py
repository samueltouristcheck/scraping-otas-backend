import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from scraping.common.browser_profile import random_browser_profile


class PlaywrightScraperBase:
    def __init__(self, *, max_retries: int = 3, timeout_ms: int = 30000, headless: bool = True):
        self.max_retries = max_retries
        self.timeout_ms = timeout_ms
        self.headless = headless
        self.logger = logging.getLogger(self.__class__.__name__)
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def _ensure_browser(self) -> Browser:
        if self._browser is not None:
            return self._browser

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        return self._browser

    async def _new_context(self, locale: str = "en-GB", timezone_id: str = "Europe/Madrid") -> BrowserContext:
        browser = await self._ensure_browser()
        profile = random_browser_profile(locale=locale, timezone_id=timezone_id)
        return await browser.new_context(
            user_agent=profile.user_agent,
            viewport=profile.viewport,
            locale=profile.locale,
            timezone_id=profile.timezone_id,
            java_script_enabled=True,
            ignore_https_errors=False,
            extra_http_headers={"Accept-Language": profile.locale},
        )

    async def with_retries(self, operation: Callable[[], Awaitable[Page]]) -> Page:
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.max_retries),
                wait=wait_exponential_jitter(initial=1, max=10),
                retry=retry_if_exception_type(Exception),
                reraise=True,
            ):
                with attempt:
                    return await operation()
        except Exception as exc:
            self.logger.exception("scrape_operation_retries_exhausted")
            raise RuntimeError("Scrape operation failed after retries") from exc

    async def fetch_page(self, url: str, *, locale: str = "en-GB", timezone_id: str = "Europe/Madrid") -> tuple[Page, BrowserContext]:
        async def _operation() -> Page:
            context = await self._new_context(locale=locale, timezone_id=timezone_id)
            try:
                page = await context.new_page()

                await asyncio.sleep(random.uniform(0.2, 1.1))
                await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                await page.wait_for_timeout(int(random.uniform(450, 1400)))
                return page
            except Exception:
                await context.close()
                raise

        page = await self.with_retries(_operation)
        context = page.context
        return page, context

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
