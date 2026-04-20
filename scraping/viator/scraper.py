"""Viator scraper.

Flow per horizon date
─────────────────────
1. Open the attraction **listing page**
   e.g. https://www.viator.com/Barcelona-attractions/Sagrada-Familia/d562-a845
2. Collect links to individual **tour detail pages**
   (slug pattern: /tours/<dest>/<name>/d<id>-<code>)
3. For each detail page:
   a. Ensure travelers = 1 adult.
   b. Click **"Check Availability"**.
   c. Click the **target date** in the calendar widget (for future dates).
   d. Iterate each **option card** (radio items) to reveal time-slots.
   e. Parse: option name · time-slots · price · seats · availability.
4. Build ``ScrapedPricePoint`` / ``ScrapedAvailabilityPoint`` rows.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from playwright.async_api import BrowserContext, Error as PlaywrightError
from playwright.async_api import Page

from core.contracts import OtaScraper
from models.dto import HorizonRequest, ScrapeResult, ScrapedAvailabilityPoint, ScrapedPricePoint
from scraping.base.playwright_scraper import PlaywrightScraperBase
from scraping.viator.selectors import (
    CHECK_AVAILABILITY_LABELS,
    DETAIL_SLUG_PATTERN,
    OPTION_CARD_SELS,
    UNAVAILABLE_MARKERS,
)

# ------------------------------------------------------------------ #
# Compiled patterns                                                    #
# ------------------------------------------------------------------ #
_PRICE_RE = re.compile(
    r"(?:(?:€|EUR)\s*([0-9]+(?:[.,][0-9]{1,2})?)"
    r"|([0-9]+(?:[.,][0-9]{1,2})?)\s*(?:€|EUR))",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)(?:\s*[AP]M)?\b", re.IGNORECASE)
# Matches time ranges like "12:00 - 12:05" → captures only start
_TIME_RANGE_RE = re.compile(
    r"\b((?:[01]?\d|2[0-3]):[0-5]\d(?:\s*[AP]M)?)\s*[-\u2013\u2014]\s*(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*[AP]M)?\b",
    re.IGNORECASE,
)
# 12-hour time with AM/PM (Viator uses this format)
_TIME_12H_RE = re.compile(r"\b(1[0-2]|0?[1-9]):([0-5]\d)\s*(AM|PM)\b", re.IGNORECASE)
_SPACE = re.compile(r"\s+")
_SEATS_RE = re.compile(
    r"only\s+(\d+)\s+spots?\s+(?:left|available)"
    r"|solo\s+quedan?\s+(\d+)\s+plazas?\s+disponibles?",
    re.IGNORECASE,
)
_BLOCKED_RE = re.compile(
    r"ray\s+id|access\s+denied|attention\s+required"
    r"|captcha|robot|automated",
    re.IGNORECASE,
)
_DETAIL_SLUG_RE = re.compile(DETAIL_SLUG_PATTERN)

# Lines to skip when hunting for the option name inside a card
_NAME_SKIP = (
    "sold out",
    "only",
    "likely to sell out",
    "bestseller",
    "best seller",
    "free cancellation",
    "lowest price guarantee",
    "reserve now",
    "book now",
    "from €",
    "from $",
    "per person",
    "1 adult",
)

# Language term → canonical English label
_LANG_TERMS: dict[str, str] = {}
for _canon, _vars in {
    "english": ["english", "inglés", "ingles"],
    "spanish": ["spanish", "español", "espanol", "castellano"],
    "french": ["french", "francés", "frances"],
    "german": ["german", "alemán", "aleman"],
    "italian": ["italian", "italiano"],
    "portuguese": ["portuguese", "portugués", "portugues"],
    "catalan": ["catalan", "catalán", "catala"],
}.items():
    for _v in _vars:
        _LANG_TERMS[_v.lower()] = _canon


# ================================================================== #
#  Scraper                                                             #
# ================================================================== #
class ViatorScraper(PlaywrightScraperBase, OtaScraper):
    ota_name = "viator"

    def __init__(
        self,
        *,
        max_retries: int = 3,
        timeout_ms: int = 30_000,
        headless: bool = True,
    ):
        super().__init__(max_retries=max_retries, timeout_ms=timeout_ms, headless=headless)
        self.logger = logging.getLogger("scraping.viator")

    # ---------------------------------------------------------------- #
    # Public entry-point (single horizon)                               #
    # ---------------------------------------------------------------- #
    async def scrape_one_horizon(
        self,
        source_url: str,
        hz: HorizonRequest,
        *,
        captured_at: datetime | None = None,
        product_name: str | None = None,
        raw_excerpt: str | None = None,
    ) -> ScrapeResult:
        if captured_at is None:
            captured_at = datetime.now(UTC)

        prices: list[ScrapedPricePoint] = []
        avail: list[ScrapedAvailabilityPoint] = []
        langs: set[str] = set()
        opts: set[str] = set()
        slots: set[time] = set()

        try:
            page, ctx = await self.fetch_page(
                source_url,
                locale="en-GB",
                timezone_id="Europe/Madrid",
            )
        except Exception as exc:
            self.logger.warning("listing_fetch_failed", extra={"url": source_url, "err": str(exc)})
            return ScrapeResult(
                ota_name=self.ota_name,
                source_url=source_url,
                product_name=product_name,
                captured_at=captured_at,
                prices=[],
                availability=[],
            )

        try:
            if product_name is None:
                product_name = await page.title()

            body = await page.inner_text("body")
            if _BLOCKED_RE.search(body):
                self.logger.warning("blocked_page", extra={"url": source_url})
                return ScrapeResult(
                    ota_name=self.ota_name,
                    source_url=source_url,
                    product_name=product_name,
                    captured_at=captured_at,
                    prices=[],
                    availability=[],
                )
            if raw_excerpt is None:
                raw_excerpt = body[:3000]

            langs.update(self._find_languages(body))

            # Scroll to load lazy-rendered tour cards
            await self._scroll_to_load(page)

            detail_urls = await self._collect_detail_urls(page, base_url=source_url)
            detail_urls = self._resolve_detail_urls(source_url, detail_urls)
            self.logger.info("detail_urls", extra={"n": len(detail_urls), "sample": detail_urls[:5]})

            options: list[dict] = []
            # Reuse same context so Viator sees normal browsing (shared cookies/session)
            for durl in detail_urls[:10]:
                page_opts = await self._scrape_detail_in_ctx(ctx, durl, target_date=hz.target_date)
                options.extend(page_opts)

            for o in options:
                n = o.get("option_name")
                if n:
                    opts.add(n)
                for s in o.get("slot_times", []):
                    if isinstance(s, time):
                        slots.add(s)

            p, a = self._build_points(hz.target_date, hz.horizon_days, captured_at, options)
            prices.extend(p)
            avail.extend(a)

        finally:
            try:
                await ctx.close()
            except PlaywrightError:
                pass

        return ScrapeResult(
            ota_name=self.ota_name,
            source_url=source_url,
            product_name=product_name,
            captured_at=captured_at,
            languages=sorted(langs),
            options=sorted(opts),
            slots=sorted(slots),
            prices=prices,
            availability=avail,
            raw_excerpt=raw_excerpt,
        )

    # ---------------------------------------------------------------- #
    # Public entry-point (multi-horizon)                                #
    # ---------------------------------------------------------------- #
    async def scrape(
        self,
        source_url: str,
        horizons: list[HorizonRequest],
    ) -> ScrapeResult:
        captured_at = datetime.now(UTC)
        product_name: str | None = None
        raw_excerpt: str | None = None
        all_prices: list[ScrapedPricePoint] = []
        all_avail: list[ScrapedAvailabilityPoint] = []
        agg_langs: set[str] = set()
        agg_opts: set[str] = set()
        agg_slots: set[time] = set()

        try:
            for hz in horizons:
                try:
                    page, ctx = await self.fetch_page(
                        source_url,
                        locale="en-GB",
                        timezone_id="Europe/Madrid",
                    )
                except Exception as exc:
                    self.logger.warning(
                        "listing_fetch_failed", extra={"url": source_url, "err": str(exc)}
                    )
                    continue

                try:
                    if product_name is None:
                        product_name = await page.title()

                    body = await page.inner_text("body")
                    if _BLOCKED_RE.search(body):
                        self.logger.warning("blocked_page", extra={"url": source_url})
                        continue
                    if raw_excerpt is None:
                        raw_excerpt = body[:3000]

                    agg_langs.update(self._find_languages(body))

                    # Scroll to load lazy-rendered tour cards
                    await self._scroll_to_load(page)

                    detail_urls = await self._collect_detail_urls(page, base_url=source_url)
                    detail_urls = self._resolve_detail_urls(source_url, detail_urls)
                    self.logger.info(
                        "detail_urls",
                        extra={"n": len(detail_urls), "sample": detail_urls[:5]},
                    )

                    options: list[dict] = []
                    # Reuse same context so Viator sees normal browsing (shared cookies/session)
                    for durl in detail_urls[:10]:
                        page_opts = await self._scrape_detail_in_ctx(ctx, durl, target_date=hz.target_date)
                        options.extend(page_opts)

                    self.logger.info(
                        "horizon_options",
                        extra={
                            "date": hz.target_date.isoformat(),
                            "total": len(options),
                            "with_slot": sum(1 for o in options if o.get("slot_times")),
                        },
                    )

                    for o in options:
                        n = o.get("option_name")
                        if n:
                            agg_opts.add(n)
                        for s in o.get("slot_times", []):
                            if isinstance(s, time):
                                agg_slots.add(s)

                    p, a = self._build_points(
                        hz.target_date, hz.horizon_days, captured_at, options
                    )
                    all_prices.extend(p)
                    all_avail.extend(a)

                    if not options:
                        fp = await self._fallback_price(page)
                        if fp is not None:
                            all_prices.append(
                                ScrapedPricePoint(
                                    target_date=hz.target_date,
                                    horizon_days=hz.horizon_days,
                                    observed_at=captured_at,
                                    currency_code="EUR",
                                    list_price=fp,
                                    final_price=fp,
                                )
                            )
                        all_avail.append(
                            ScrapedAvailabilityPoint(
                                target_date=hz.target_date,
                                horizon_days=hz.horizon_days,
                                observed_at=captured_at,
                                is_available=not self._is_unavailable(body),
                            )
                        )
                finally:
                    try:
                        await ctx.close()
                    except PlaywrightError:
                        pass

            return ScrapeResult(
                ota_name=self.ota_name,
                source_url=source_url,
                product_name=product_name,
                captured_at=captured_at,
                languages=sorted(agg_langs),
                options=sorted(agg_opts),
                slots=sorted(agg_slots),
                prices=all_prices,
                availability=all_avail,
                raw_excerpt=raw_excerpt,
            )
        finally:
            await self.close()

    # ---------------------------------------------------------------- #
    # Detail page (shared context)                                      #
    # ---------------------------------------------------------------- #
    async def _scrape_detail_in_ctx(
        self,
        ctx: "BrowserContext",
        url: str,
        *,
        target_date: date | None = None,
    ) -> list[dict]:
        """Open a Viator tour detail page in an existing browser context.

        Reusing the context means Viator sees this as continued browsing
        from the listing page (same cookies/session), avoiding bot detection.
        """
        import random as _random
        dated_url = self._url_for_date(url, target_date) if target_date else url
        page: Page | None = None
        try:
            page = await ctx.new_page()
            await page.goto(dated_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            # Mimic human reading time
            await page.wait_for_timeout(int(_random.uniform(1500, 3000)))
            # Scroll a bit to trigger lazy rendering
            await self._scroll_to_load(page)

            title = await self._page_h1(page)
            body = await page.inner_text("body")

            # Detect bot-block (Cloudflare / Viator challenge)
            if self._is_bot_blocked(body, title):
                self.logger.warning("detail_bot_blocked", extra={"url": dated_url})
                return []

            self.logger.info("detail_page", extra={"url": dated_url, "title": title})

            # ── 1. Ensure 1 adult selected ────────────────────────────
            await self._set_one_adult(page)

            # ── 2. Select future date in calendar (if needed) ─────────
            if target_date is not None:
                await self._select_date(page, target_date)

            # ── 3. Click "Check Availability" ────────────────────────
            clicked = await self._click_check_availability(page)
            self.logger.info("check_availability", extra={"url": dated_url, "clicked": clicked})

            # ── 4. Wait for options to appear ─────────────────────────
            await page.wait_for_timeout(3000)

            # ── 5. Read option cards ──────────────────────────────────
            options = await self._read_option_cards(page, page_title=title)

            # ── 6. Fallback: build single option from page text ───────
            if not options and title:
                body_after = await page.inner_text("body")
                times = self._find_times(body_after)
                price = self._find_first_price(body_after)
                seats = self._find_seats(body_after)
                lang_list = self._find_languages(body_after)
                lang = lang_list[0] if lang_list else None
                if times or price:
                    norm = self._norm(title)
                    options.append(
                        {
                            "option_name": norm,
                            "price": price,
                            "slot_times": times,
                            "language_code": lang,
                            "is_available": not self._is_unavailable(body_after),
                            "seats_available": seats,
                            "detail_tour_name": norm,
                        }
                    )

            # Annotate with normalised tour title
            norm_detail = self._norm(title) if title else None
            for opt in options:
                opt.setdefault("detail_tour_name", norm_detail)

            return options

        except Exception:
            self.logger.debug("detail_fetch_fail", extra={"url": dated_url}, exc_info=True)
            return []
        finally:
            if page is not None:
                try:
                    await page.close()
                except PlaywrightError:
                    pass

    # Keep old signature for backward compatibility
    async def _scrape_detail_page(
        self, url: str, *, target_date: date | None = None
    ) -> list[dict]:
        """Fallback: open detail page in a fresh browser context."""
        dated_url = self._url_for_date(url, target_date) if target_date else url
        try:
            page, ctx = await self.fetch_page(dated_url, locale="en-GB", timezone_id="Europe/Madrid")
        except Exception:
            self.logger.debug("detail_fetch_fail", extra={"url": dated_url}, exc_info=True)
            return []
        try:
            return await self._scrape_detail_in_ctx(ctx, url, target_date=target_date)
        finally:
            try:
                await ctx.close()
            except PlaywrightError:
                pass

    # ---------------------------------------------------------------- #
    # Anti-detection helpers                                            #
    # ---------------------------------------------------------------- #
    async def _scroll_to_load(self, page: Page) -> None:
        """Scroll through the page in human-like steps to trigger lazy-loads."""
        try:
            height = await page.evaluate("document.body.scrollHeight")
            step = max(300, height // 6)
            for pos in range(0, height, step):
                await page.evaluate(f"window.scrollTo(0, {pos})")
                await page.wait_for_timeout(200)
            # Scroll back to top
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(500)
        except Exception:
            pass

    @staticmethod
    def _is_bot_blocked(body: str, title: str | None) -> bool:
        """Return True when Viator (or Cloudflare) shows a bot-challenge page."""
        if title and title.strip().lower() in ("viator.com", "just a moment...", "attention required"):
            return True
        low = body.lower()
        bot_markers = [
            "ray id",
            "cloudflare",
            "please verify you are a human",
            "enable javascript and cookies",
            "checking your browser",
            "access denied",
            "captcha",
        ]
        return any(m in low for m in bot_markers)

    # ---------------------------------------------------------------- #
    # Set 1 adult traveler                                              #
    # ---------------------------------------------------------------- #
    async def _set_one_adult(self, page: Page) -> None:
        """Ensure the travelers count is set to 1 adult.

        On Viator the default is often 2 adults; we reset it to 1
        so that prices are always quoted per-person / 1 adult.
        """
        # Common traveler-picker selectors
        traveler_btn_sels = [
            "[data-testid='traveler-picker-trigger']",
            "[data-testid='travelers-picker']",
            "button[aria-label*='traveler']",
            "button[aria-label*='Traveler']",
            "button:has-text('2 Adults')",
            "button:has-text('2 Travelers')",
            "[class*='TravelerPicker']",
            "[class*='travelerPicker']",
            # Right-side booking widget
            ".booking-widget button[aria-haspopup]",
        ]

        opened = False
        for sel in traveler_btn_sels:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(timeout=2000)
                    await page.wait_for_timeout(800)
                    opened = True
                    break
            except Exception:
                continue

        if not opened:
            # Try clicking on the travelers section by text
            for lbl in ("2 Adults", "2 Travelers", "Adults", "Travelers"):
                try:
                    btn = page.locator(f"button:has-text('{lbl}')").first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click(timeout=2000)
                        await page.wait_for_timeout(800)
                        opened = True
                        break
                except Exception:
                    continue

        if not opened:
            self.logger.debug("traveler_picker_not_found")
            return

        # Decrement adult count until 1
        decrement_sels = [
            "[data-testid='traveler-type-stepper-decrement-ADULT']",
            "[data-testid*='decrement'][data-testid*='adult']",
            "button[aria-label*='Decrease'][aria-label*='Adult']",
            "button[aria-label*='decrease'][aria-label*='adult']",
            "button[aria-label*='Reduce adult']",
            "[class*='decrement']",
        ]

        for _ in range(5):  # safety: at most 5 decrements
            # Check current adult count
            try:
                count_text = await page.locator("[data-testid*='stepper'][data-testid*='ADULT'] [class*='count'], [class*='stepperCount']").first.inner_text(timeout=1000)
                current = int(re.search(r"\d+", count_text).group())
                if current <= 1:
                    break
            except Exception:
                pass

            decremented = False
            for sel in decrement_sels:
                try:
                    btn = page.locator(sel).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click(timeout=1500)
                        await page.wait_for_timeout(400)
                        decremented = True
                        break
                except Exception:
                    continue
            if not decremented:
                break

        # Confirm / apply picker
        confirm_sels = [
            "button:has-text('Done')",
            "button:has-text('Apply')",
            "button:has-text('Confirm')",
            "button:has-text('Update')",
            "[data-testid='traveler-picker-done']",
        ]
        for sel in confirm_sels:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(timeout=1500)
                    await page.wait_for_timeout(600)
                    break
            except Exception:
                continue

        self.logger.debug("traveler_set_to_1")

    # ---------------------------------------------------------------- #
    # Select target date                                                #
    # ---------------------------------------------------------------- #
    async def _select_date(self, page: Page, target_date: date) -> bool:
        """Click *target_date* in the Viator date-picker widget.

        Returns True if the date was found and clicked.
        """
        iso = target_date.isoformat()   # "2026-03-15"
        day = str(target_date.day)

        # Selector variants Viator uses
        # Build platform-safe date label strings (no %-d which is Linux-only)
        day_no_pad = str(target_date.day)       # e.g. "15"  (no leading zero)
        month_name = target_date.strftime("%B") # e.g. "March"

        day_sels = [
            f"[aria-label*='{iso}']",
            f"[data-date='{iso}']",
            f"button[data-testid*='{iso}']",
            f"[data-testid='calendar-day-{iso}']",
            f"td[data-date='{iso}']",
            f"button[aria-label*='{day_no_pad} {month_name}']",
            f"button[aria-label*='{month_name} {day_no_pad}']",
        ]

        async def _try_click(selectors: list[str]) -> bool:
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.scroll_into_view_if_needed(timeout=1000)
                        await loc.click(timeout=2000)
                        await page.wait_for_timeout(1500)
                        self.logger.info("calendar_date_selected", extra={"date": iso, "sel": sel})
                        return True
                except Exception:
                    continue
            return False

        # Open the date-picker first (if it's not already open)
        date_input_sels = [
            "[data-testid='date-picker-trigger']",
            "[data-testid='date-selector']",
            "button[aria-label*='date']",
            "button[aria-label*='Date']",
            "input[type='text'][placeholder*='date' i]",
            ".date-picker-input",
            "[class*='DatePicker'] button",
        ]
        for sel in date_input_sels:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(timeout=2000)
                    await page.wait_for_timeout(800)
                    break
            except Exception:
                continue

        if await _try_click(day_sels):
            return True

        # Navigate calendar forward up to 6 months
        next_btn_sels = [
            "button[aria-label*='next month' i]",
            "button[aria-label*='siguiente mes' i]",
            "[data-testid='calendar-next-month']",
            "button[aria-label='Forward']",
            "button[class*='next']",
        ]
        for _ in range(6):
            navigated = False
            for nsel in next_btn_sels:
                try:
                    btn = page.locator(nsel).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click(timeout=2000)
                        await page.wait_for_timeout(800)
                        navigated = True
                        break
                except Exception:
                    continue
            if not navigated:
                break
            if await _try_click(day_sels):
                return True

        self.logger.debug("calendar_date_not_found", extra={"date": iso})
        return False

    # ---------------------------------------------------------------- #
    # Click "Check Availability"                                        #
    # ---------------------------------------------------------------- #
    async def _click_check_availability(self, page: Page) -> bool:
        for label in CHECK_AVAILABILITY_LABELS:
            loc = page.locator(f"button:has-text('{label}')").first
            try:
                if await loc.count() == 0:
                    continue
                if not await loc.is_visible():
                    continue
                try:
                    await loc.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass
                await loc.click(timeout=4000)
                await page.wait_for_timeout(3000)
                return True
            except Exception:
                try:
                    await page.locator(f"button:has-text('{label}')").first.click(
                        timeout=3000, force=True
                    )
                    await page.wait_for_timeout(3000)
                    return True
                except Exception:
                    continue

        # JS fallback
        try:
            clicked = await page.evaluate(
                """() => {
                    const labels = ['check availability', 'comprobar disponibilidad', 'ver disponibilidad'];
                    for (const el of document.querySelectorAll('button, a')) {
                        const t = (el.innerText || '').trim().toLowerCase();
                        if (labels.some(l => t.includes(l))) { el.click(); return true; }
                    }
                    return false;
                }"""
            )
            if clicked:
                await page.wait_for_timeout(3000)
                return True
        except Exception:
            pass

        self.logger.warning("check_availability_btn_not_found")
        return False

    # ---------------------------------------------------------------- #
    # Read option cards                                                 #
    # ---------------------------------------------------------------- #
    async def _read_option_cards(
        self,
        page: Page,
        *,
        page_title: str | None,
    ) -> list[dict]:
        """Read all option cards/radio items from the availability section.

        Viator shows options as a list of radio-button style cards.
        Each option may contain: name, price, times (only after clicking).
        We click each option to expand time slots, then read the text.
        """
        # ── Collect raw text from all found option cards ─────────────
        raw_cards: list[tuple[str, int]] = []  # (text, card_index)
        used_sel: str | None = None

        for sel in OPTION_CARD_SELS:
            try:
                n = await page.locator(sel).count()
                if n == 0:
                    continue
                cards_for_sel: list[tuple[str, int]] = []
                for i in range(min(n, 20)):
                    try:
                        t = await page.locator(sel).nth(i).inner_text(timeout=2000)
                        if t.strip():
                            cards_for_sel.append((t.strip(), i))
                    except Exception:
                        continue
                if cards_for_sel:
                    raw_cards = cards_for_sel
                    used_sel = sel
                    break
            except Exception:
                continue

        # ── Broad fallback: look inside booking widget ----------------
        if not raw_cards:
            try:
                panel_sels = [
                    "[data-testid='booking-widget']",
                    "[data-testid='availability-panel']",
                    "[class*='BookingWidget']",
                    "#booking-section",
                    ".booking-widget",
                ]
                for psel in panel_sels:
                    panel = page.locator(psel).first
                    if await panel.count() > 0:
                        txt = await panel.inner_text(timeout=3000)
                        if txt.strip():
                            raw_cards = [(txt.strip(), 0)]
                            used_sel = psel
                            break
            except Exception:
                pass

        self.logger.info(
            "option_cards_raw",
            extra={
                "selector": used_sel,
                "count": len(raw_cards),
                "previews": [c[0][:150] for c in raw_cards[:5]],
            },
        )

        if not raw_cards:
            return []

        # ── Click each option card to reveal time slots ───────────────
        enriched = await self._click_options_and_enrich(page, raw_cards, used_sel)

        results: list[dict] = []
        for card_text in enriched:
            parsed = self._parse_card(card_text, page_title=page_title)
            if parsed:
                results.append(parsed)

        return results

    async def _click_options_and_enrich(
        self,
        page: Page,
        raw_cards: list[tuple[str, int]],
        used_sel: str | None,
    ) -> list[str]:
        """Click each option to expand time slots, then capture inner_text."""
        enriched: list[str] = [text for text, _ in raw_cards]

        if not used_sel:
            return enriched

        try:
            n = await page.locator(used_sel).count()
        except Exception:
            return enriched

        if n == 0:
            return enriched

        for i, (original_text, card_idx) in enumerate(raw_cards[:15]):
            try:
                card = page.locator(used_sel).nth(card_idx)

                # ── 1. Scroll into view ───────────────────────────────
                try:
                    await card.scroll_into_view_if_needed(timeout=1500)
                except Exception:
                    pass

                # ── 2. Click to select / expand ───────────────────────
                try:
                    await card.click(timeout=3000)
                    await page.wait_for_timeout(1500)
                except Exception:
                    try:
                        await card.click(timeout=2000, force=True)
                        await page.wait_for_timeout(1500)
                    except Exception:
                        continue

                # ── 3. Read enriched text (now includes time slots) ───
                try:
                    new_text = await card.inner_text(timeout=2000)
                    if new_text.strip():
                        enriched[i] = new_text.strip()
                except Exception:
                    pass

                # ── 4. Also try reading the expanded section below ────
                try:
                    expanded_sels = [
                        "[data-testid='timeslot-picker']",
                        "[data-testid='time-slot-picker']",
                        "[class*='TimeSlotPicker']",
                        "[class*='timeslotPicker']",
                        "[class*='AvailableTimes']",
                    ]
                    for esel in expanded_sels:
                        expanded = page.locator(esel).first
                        if await expanded.count() > 0:
                            extra = await expanded.inner_text(timeout=1500)
                            if extra.strip():
                                enriched[i] = enriched[i] + "\n" + extra.strip()
                            break
                except Exception:
                    pass

            except Exception as exc:
                self.logger.debug("card_click_error", extra={"i": i, "err": str(exc)})
                continue

        return enriched

    # ---------------------------------------------------------------- #
    # Card parsing                                                      #
    # ---------------------------------------------------------------- #
    def _parse_card(
        self,
        text: str,
        *,
        page_title: str | None = None,
    ) -> dict | None:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if len(lines) < 2:
            return None

        name = self._find_option_name(lines) or page_title
        if not name:
            return None

        norm_name = self._norm(name)

        times = self._find_times(text)
        price = self._find_first_price(text)
        seats = self._find_seats(text)
        lang_list = self._find_languages(text)
        lang = lang_list[0] if lang_list else None

        return {
            "option_name": norm_name,
            "price": price,
            "slot_times": times,
            "language_code": lang,
            "is_available": not self._is_unavailable(text),
            "seats_available": seats,
        }

    @staticmethod
    def _find_option_name(lines: list[str]) -> str | None:
        for line in lines[:10]:
            low = line.lower()
            if any(low.startswith(p) or p in low for p in _NAME_SKIP):
                continue
            if "€" in line or "EUR" in line.upper() or "$" in line:
                continue
            if re.match(r"^\d+:\d+", line):  # time token
                continue
            if re.match(r"^(AM|PM|am|pm)$", line.strip()):
                continue
            if len(line) < 5:
                continue
            return line
        return None

    # ---------------------------------------------------------------- #
    # Listing page – collect detail URLs                                #
    # ---------------------------------------------------------------- #
    async def _collect_detail_urls(
        self,
        page: Page,
        *,
        base_url: str,
    ) -> list[str]:
        raw = await page.eval_on_selector_all(
            "a[href]",
            """els => els.map(el => ({
                href: el.getAttribute('href') || '',
                text: (
                    el.closest('article, li, [data-test-id], [class*=\"ProductCard\"]') || el
                ).innerText?.slice(0, 300) || ''
            }))""",
        )

        urls: list[str] = []
        seen: set[str] = set()
        for item in raw:
            href = str(item.get("href", "")).strip()
            if not href:
                continue

            absolute = urljoin(base_url, href).split("#")[0].split("?")[0]
            path = urlsplit(absolute).path

            if not _DETAIL_SLUG_RE.search(path):
                continue
            if absolute in seen:
                continue

            seen.add(absolute)
            urls.append(absolute)

        self.logger.info("collected_detail_urls", extra={"count": len(urls), "urls": urls[:5]})
        return urls

    def _resolve_detail_urls(self, source_url: str, collected: list[str]) -> list[str]:
        """Si la URL monitorizada ya es una ficha /tours/…/d562-XXX, no hay enlaces en grid → usarla sola."""
        if collected:
            return collected
        p = urlsplit(source_url)
        if "/tours/" in p.path and _DETAIL_SLUG_RE.search(p.path):
            clean = urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), "", ""))
            self.logger.info("detail_urls_fallback_single_tour", extra={"url": clean})
            return [clean]
        return []

    # ---------------------------------------------------------------- #
    # Result-point builders                                             #
    # ---------------------------------------------------------------- #
    @staticmethod
    def _build_points(
        target_date: date,
        horizon_days: int,
        observed_at: datetime,
        option_details: list[dict],
    ) -> tuple[list[ScrapedPricePoint], list[ScrapedAvailabilityPoint]]:
        prices: list[ScrapedPricePoint] = []
        avail: list[ScrapedAvailabilityPoint] = []
        seen_p: set[tuple] = set()
        seen_a: set[tuple] = set()

        for d in option_details:
            name = d.get("option_name")
            price = d.get("price")
            lang = d.get("language_code")
            is_av = d.get("is_available", True)
            seats = d.get("seats_available")
            detail_tour_name = d.get("detail_tour_name")
            slots = [s for s in d.get("slot_times", []) if isinstance(s, time)] or [None]

            for slot in slots:
                key = (name, slot, lang)
                if price is not None and key not in seen_p:
                    seen_p.add(key)
                    prices.append(
                        ScrapedPricePoint(
                            target_date=target_date,
                            horizon_days=horizon_days,
                            observed_at=observed_at,
                            slot_time=slot,
                            language_code=lang,
                            option_name=name,
                            currency_code="EUR",
                            list_price=price,
                            final_price=price,
                            detail_tour_name=detail_tour_name,
                        )
                    )
                if key not in seen_a:
                    seen_a.add(key)
                    avail.append(
                        ScrapedAvailabilityPoint(
                            target_date=target_date,
                            horizon_days=horizon_days,
                            observed_at=observed_at,
                            slot_time=slot,
                            language_code=lang,
                            option_name=name,
                            is_available=is_av,
                            seats_available=seats,
                            detail_tour_name=detail_tour_name,
                        )
                    )

        return prices, avail

    # ---------------------------------------------------------------- #
    # Small helpers                                                     #
    # ---------------------------------------------------------------- #
    @staticmethod
    def _url_for_date(source_url: str, target_date: date) -> str:
        """Inject date query-params into a Viator detail URL."""
        p = urlsplit(source_url)
        q = dict(parse_qsl(p.query, keep_blank_values=True))
        d = target_date.isoformat()
        # Viator uses 'date' or 'startDate' query-param
        q["date"] = d
        return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))

    @staticmethod
    def _norm(value: str) -> str:
        n = unicodedata.normalize("NFKD", value)
        stripped = "".join(c for c in n if not unicodedata.combining(c))
        return _SPACE.sub(" ", stripped).strip().lower()

    @staticmethod
    def _parse_price(raw: str) -> Decimal | None:
        tokens = [
            m.group(1) or m.group(2)
            for m in _PRICE_RE.finditer(raw)
            if m.group(1) or m.group(2)
        ]
        if tokens:
            norm = tokens[0].replace(",", ".")
        else:
            compact = raw.strip().replace("\u00a0", " ").replace(" ", "")
            if not re.fullmatch(r"[0-9]+(?:[.,][0-9]{1,2})?", compact):
                return None
            norm = compact.replace(",", ".")
        try:
            return Decimal(norm)
        except ArithmeticError:
            return None

    @staticmethod
    def _find_times(text: str) -> list[time]:
        """Extract time slots from card text (supports 12h AM/PM and 24h)."""
        cleaned = _TIME_RANGE_RE.sub(r"\1", text)
        seen: set[time] = set()
        result: list[time] = []

        # 12-hour format (Viator default: "1:15 PM", "9:10 AM")
        for h_str, m_str, ampm in _TIME_12H_RE.findall(cleaned):
            h = int(h_str)
            m = int(m_str)
            if ampm.upper() == "PM" and h != 12:
                h += 12
            elif ampm.upper() == "AM" and h == 12:
                h = 0
            try:
                t = time(h, m)
                if t not in seen:
                    seen.add(t)
                    result.append(t)
            except ValueError:
                continue

        # 24-hour format fallback (only when no 12h slots found)
        if not result:
            for h_str, m_str in _TIME_RE.findall(cleaned):
                try:
                    t = time(int(h_str), int(m_str))
                    if t not in seen:
                        seen.add(t)
                        result.append(t)
                except ValueError:
                    continue

        result.sort()
        return result

    @staticmethod
    def _find_first_price(text: str) -> Decimal | None:
        matches = list(_PRICE_RE.finditer(text))
        if not matches:
            return None
        # Last price is usually the final/discounted price
        last = matches[-1]
        token = last.group(1) or last.group(2)
        return ViatorScraper._parse_price(token) if token else None

    @staticmethod
    def _find_seats(text: str) -> int | None:
        m = _SEATS_RE.search(text)
        if not m:
            return None
        for g in m.groups():
            if g is not None:
                try:
                    return int(g)
                except ValueError:
                    continue
        return None

    @staticmethod
    def _find_languages(text: str) -> list[str]:
        lowered = ViatorScraper._norm(text)
        found: set[str] = set()
        for term, canonical in _LANG_TERMS.items():
            if term in lowered:
                found.add(canonical)
        return sorted(found)

    @staticmethod
    def _is_unavailable(text: str) -> bool:
        low = text.lower()
        return any(marker in low for marker in UNAVAILABLE_MARKERS)

    async def _page_h1(self, page: Page) -> str | None:
        for sel in ("h1", "[data-testid='product-title']", "[class*='ProductTitle']"):
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    txt = await loc.inner_text(timeout=2000)
                    if txt.strip():
                        return txt.strip()
            except Exception:
                continue
        return None

    @staticmethod
    def default_horizons(
        reference_date: date | None = None,
        daily_window_days: int = 7,
    ) -> list[HorizonRequest]:
        today = reference_date or datetime.now(UTC).date()
        bound = max(0, min(180, daily_window_days))
        return [
            HorizonRequest(horizon_days=d, target_date=today + timedelta(days=d))
            for d in range(bound + 1)
        ]

    async def _fallback_price(self, page: Page) -> Decimal | None:
        """Try JSON-LD or price-selector extraction as a last resort."""
        try:
            ld_blocks = await page.eval_on_selector_all(
                "script[type='application/ld+json']",
                "els => els.map(e => e.textContent)",
            )
            for block in ld_blocks:
                data = json.loads(block)
                price_raw = (
                    data.get("offers", {}).get("price")
                    or data.get("price")
                )
                if price_raw is not None:
                    p = ViatorScraper._parse_price(str(price_raw))
                    if p:
                        return p
        except Exception:
            pass

        for sel in (
            "[data-testid*='price']",
            "[class*='price']",
            "[class*='Price']",
            ".booking-widget [class*='price']",
        ):
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    txt = await loc.inner_text(timeout=1500)
                    p = self._find_first_price(txt)
                    if p:
                        return p
            except Exception:
                continue

        return None
