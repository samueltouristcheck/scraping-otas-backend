"""GetYourGuide scraper.

Flow per horizon date
─────────────────────
1. Open the attraction **listing page** (search-results grid).
2. Collect links to individual **tour detail pages** (``-tNNNN`` slugs).
3. For each detail page:
   a. Click **"Ver disponibilidad"**.
   b. Wait for the availability panel to render.
   c. Click the **target date** in the calendar widget (needed for future dates).
   d. Click each **option card** to reveal its time-slots / seats.
   e. Parse: option name · time-slots · price · seats · language.
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

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from core.contracts import OtaScraper
from models.dto import HorizonRequest, ScrapeResult, ScrapedAvailabilityPoint, ScrapedPricePoint
from scraping.base.playwright_scraper import PlaywrightScraperBase
from scraping.getyourguide.selectors import UNAVAILABLE_MARKERS

# ------------------------------------------------------------------ #
# Compiled patterns                                                    #
# ------------------------------------------------------------------ #
_PRICE_RE = re.compile(
    r"(?:(?:€|EUR)\s*([0-9]+(?:[.,][0-9]{1,2})?)"
    r"|([0-9]+(?:[.,][0-9]{1,2})?)\s*(?:€|EUR))",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
# Matches a time range like "12:00 - 12:05" or "10:30–10:31"; captures only the start time.
_TIME_RANGE_RE = re.compile(
    r"\b((?:[01]?\d|2[0-3]):[0-5]\d)\s*[-\u2013\u2014]\s*(?:[01]?\d|2[0-3]):[0-5]\d\b"
)
_SPACE = re.compile(r"\s+")
_SEATS_RE = re.compile(
    r"solo\s+quedan?\s+(\d+)\s+plazas?\s+disponibles?"
    r"|only\s+(\d+)\s+spots?\s+(?:left|available)",
    re.IGNORECASE,
)
_BLOCKED_RE = re.compile(
    r"ray\s+id|se\s+ha\s+producido\s+un\s+error"
    r"|access\s+denied|attention\s+required",
    re.IGNORECASE,
)
_DETAIL_SLUG_RE = re.compile(r"-t\d+/?$")

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

# Lines to skip when hunting for the option name inside a card
_NAME_SKIP = (
    "solo queda",
    "only",
    "se agota",
    "nuevo",
    "new",
    "mejor valorados",
    "nuestra elección",
    "nuestra eleccion",
)


# ================================================================== #
#  Scraper                                                             #
# ================================================================== #
class GetYourGuideScraper(PlaywrightScraperBase, OtaScraper):
    ota_name = "getyourguide"

    def __init__(
        self,
        *,
        max_retries: int = 3,
        timeout_ms: int = 30_000,
        headless: bool = True,
    ):
        super().__init__(max_retries=max_retries, timeout_ms=timeout_ms, headless=headless)
        self.logger = logging.getLogger("scraping.getyourguide")

    # ---------------------------------------------------------------- #
    # Public entry-point                                                #
    # ---------------------------------------------------------------- #
    async def scrape_one_horizon(
        self,
        source_url: str,
        hz: "HorizonRequest",
        *,
        captured_at: "datetime | None" = None,
        product_name: "str | None" = None,
        raw_excerpt: "str | None" = None,
    ) -> "ScrapeResult":
        """Scrape a single horizon date and return a partial ScrapeResult.

        Unlike ``scrape()``, this method does NOT call ``self.close()`` so
        the caller can reuse the same browser session across multiple horizons.
        """
        from datetime import datetime
        if captured_at is None:
            captured_at = datetime.now(UTC)

        prices: list[ScrapedPricePoint] = []
        avail: list[ScrapedAvailabilityPoint] = []
        langs: set[str] = set()
        opts: set[str] = set()
        slots: set[time] = set()

        listing_url = self._url_for_date(source_url, hz.target_date)

        try:
            page, ctx = await self.fetch_page(
                listing_url,
                locale="es-ES",
                timezone_id="Europe/Madrid",
            )
        except Exception as exc:
            self.logger.warning(
                "listing_fetch_failed",
                extra={"url": listing_url, "err": str(exc)},
            )
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
                self.logger.warning("blocked_page", extra={"url": listing_url})
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

            await self._dismiss_consent_dialogs(page)
            await self._scroll_listing_for_lazy_links(page)

            detail_urls = await self._collect_detail_urls(page, base_url=listing_url)
            if not detail_urls:
                # Listados perezosos o hub sin -t en el HTML inicial: usar la propia URL del listado
                clean = urlsplit(listing_url)._replace(query="", fragment="")
                fallback = urlunsplit(clean)
                self.logger.info(
                    "detail_urls_empty_using_listing_fallback",
                    extra={"url": fallback},
                )
                detail_urls = [fallback]

            self.logger.info(
                "detail_urls",
                extra={"n": len(detail_urls), "sample": detail_urls[:5]},
            )

            options: list[dict] = []
            for durl in detail_urls[:10]:
                dated = self._url_for_date(durl, hz.target_date)
                page_opts = await self._scrape_detail_page(dated, target_date=hz.target_date)
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
                    opts.add(n)
                for s in o.get("slot_times", []):
                    if isinstance(s, time):
                        slots.add(s)

            p, a = self._build_points(hz.target_date, hz.horizon_days, captured_at, options)
            prices.extend(p)
            avail.extend(a)

            if not options:
                fp = await self._fallback_price(page)
                if fp is not None:
                    prices.append(
                        ScrapedPricePoint(
                            target_date=hz.target_date,
                            horizon_days=hz.horizon_days,
                            observed_at=captured_at,
                            currency_code="EUR",
                            list_price=fp,
                            final_price=fp,
                        )
                    )
                avail.append(
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
            languages=sorted(langs),
            options=sorted(opts),
            slots=sorted(slots),
            prices=prices,
            availability=avail,
            raw_excerpt=raw_excerpt,
        )

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
                listing_url = self._url_for_date(source_url, hz.target_date)

                # ── 1. Open listing page ──────────────────────────────
                try:
                    page, ctx = await self.fetch_page(
                        listing_url,
                        locale="es-ES",
                        timezone_id="Europe/Madrid",
                    )
                except Exception as exc:
                    self.logger.warning(
                        "listing_fetch_failed",
                        extra={"url": listing_url, "err": str(exc)},
                    )
                    continue

                try:
                    if product_name is None:
                        product_name = await page.title()

                    body = await page.inner_text("body")
                    if _BLOCKED_RE.search(body):
                        self.logger.warning("blocked_page", extra={"url": listing_url})
                        continue
                    if raw_excerpt is None:
                        raw_excerpt = body[:3000]

                    langs = self._find_languages(body)
                    agg_langs.update(langs)

                    await self._dismiss_consent_dialogs(page)
                    await self._scroll_listing_for_lazy_links(page)

                    # ── 2. Collect detail-page URLs ───────────────────
                    detail_urls = await self._collect_detail_urls(
                        page, base_url=listing_url,
                    )
                    if not detail_urls:
                        clean = urlsplit(listing_url)._replace(query="", fragment="")
                        detail_urls = [urlunsplit(clean)]
                        self.logger.info(
                            "detail_urls_empty_using_listing_fallback",
                            extra={"url": detail_urls[0]},
                        )
                    self.logger.info(
                        "detail_urls",
                        extra={"n": len(detail_urls), "sample": detail_urls[:5]},
                    )

                    # ── 3. Scrape each detail page ────────────────────
                    options: list[dict] = []
                    for durl in detail_urls[:10]:
                        dated = self._url_for_date(durl, hz.target_date)
                        page_opts = await self._scrape_detail_page(
                            dated, target_date=hz.target_date
                        )
                        options.extend(page_opts)

                    self.logger.info(
                        "horizon_options",
                        extra={
                            "date": hz.target_date.isoformat(),
                            "total": len(options),
                            "with_slot": sum(
                                1
                                for o in options
                                if o.get("slot_times")
                            ),
                        },
                    )

                    # ── 4. Build result points ────────────────────────
                    for o in options:
                        n = o.get("option_name")
                        if n:
                            agg_opts.add(n)
                        for s in o.get("slot_times", []):
                            if isinstance(s, time):
                                agg_slots.add(s)

                    p, a = self._build_points(
                        hz.target_date, hz.horizon_days, captured_at, options,
                    )
                    all_prices.extend(p)
                    all_avail.extend(a)

                    # Fallback when zero options scraped
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
    # Detail page                                                       #
    # ---------------------------------------------------------------- #
    async def _scrape_detail_page(
        self, url: str, *, target_date: date | None = None
    ) -> list[dict]:
        """Open a detail page → click *Ver disponibilidad* → select date → read cards."""
        try:
            page, ctx = await self.fetch_page(
                url, locale="es-ES", timezone_id="Europe/Madrid",
            )
        except Exception:
            self.logger.debug("detail_fetch_fail", exc_info=True)
            return []

        try:
            canonical = self._canonical_gyg_product_url(url)
            await self._dismiss_consent_dialogs(page)

            body = await page.inner_text("body")
            if _BLOCKED_RE.search(body):
                return []

            title = await self._page_h1(page)

            # Detect homepage redirect (GYG sometimes redirects invalid URLs)
            if title and self._norm(title).startswith("descubre y reserva"):
                self.logger.debug("homepage_redirect", extra={"url": url})
                return []

            clicked = await self._click_ver_disponibilidad(page)
            self.logger.info(
                "ver_disponibilidad",
                extra={"url": url, "clicked": clicked, "title": title},
            )

            # Select target date in the calendar widget (needed for future dates).
            # Even for today this is harmless – the date is usually pre-selected.
            if target_date is not None:
                date_clicked = await self._select_date_in_panel(page, target_date)
                if date_clicked:
                    # Wait for option cards to reload after the date change
                    for sel in (
                        "[id^='option-card-']",
                        "[data-test-id*='available-option-card']",
                        "[data-test-id='sdui-ba-available-option-card']",
                        ".activity-option-container",
                        "text=opciones disponibles",
                    ):
                        try:
                            await page.locator(sel).first.wait_for(timeout=4000)
                            break
                        except Exception:
                            continue

            # Read option cards from the availability panel
            options = await self._read_option_cards(page, page_title=title)

            # If no cards found, try building a single option from page text
            if not options and title:
                body_after = await page.inner_text("body")
                times = self._find_times(body_after)
                price = self._find_first_price(body_after)
                seats = self._find_seats(body_after)
                lang_list = self._find_languages(body_after)
                lang = lang_list[0] if lang_list else None
                if times or price:
                    norm = self._norm(title)
                    if norm.startswith("barcelona:"):
                        norm = norm.split(":", 1)[1].strip()
                    options.append(
                        {
                            "option_name": norm,
                            "price": price,
                            "slot_times": times,
                            "language_code": lang,
                            "is_available": not self._is_unavailable(body_after),
                            "seats_available": seats,
                        }
                    )

            # Annotate every option with the normalised parent-page title so
            # that option cards can be found when searching by the GYG product
            # name (which differs from the individual option-card names).
            norm_detail: str | None = self._norm(title) if title else None
            for opt in options:
                opt.setdefault("detail_tour_name", norm_detail)
                opt.setdefault("detail_page_url", canonical)

            return options
        finally:
            try:
                await ctx.close()
            except PlaywrightError:
                pass

    # ---------------------------------------------------------------- #
    # Calendar date selection (future dates)                           #
    # ---------------------------------------------------------------- #
    async def _select_date_in_panel(self, page: Page, target_date: date) -> bool:
        """Click *target_date* inside the availability-panel calendar.

        After "Ver disponibilidad" is clicked, GYG renders a date-picker.
        For dates other than today the scraper must explicitly click that day
        before time-slot cards appear.

        Returns True if the date was found and clicked.
        """
        iso = target_date.isoformat()           # "2026-03-15"
        day = target_date.day                   # 15

        # Selectors GYG commonly uses for individual day cells
        day_selectors = [
            f"[aria-label*='{iso}']",
            f"[data-date='{iso}']",
            f"button[data-testid*='{iso}']",
            f"td[data-date='{iso}']",
            f"[data-testid='datepicker-day-{iso}']",
            # Spanish localised form: "15 de marzo de 2026"
            f"button[aria-label*='{day} de']",
        ]

        async def _try_click(selectors: list[str]) -> bool:
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.scroll_into_view_if_needed(timeout=1000)
                        await loc.click(timeout=2000)
                        await page.wait_for_timeout(1500)
                        self.logger.info(
                            "calendar_date_selected",
                            extra={"date": iso, "selector": sel},
                        )
                        return True
                except Exception:
                    continue
            return False

        # First try without any navigation
        if await _try_click(day_selectors):
            return True

        # Navigate forward through months (up to 6) until the date appears
        next_btn_selectors = [
            "button[aria-label*='iguiente']",          # «Siguiente mes»
            "button[aria-label*='ext month']",          # «Next month»
            "button[aria-label*='siguiente mes']",
            "[data-testid='calendar-next-month']",
            "[data-testid='datepicker-next-month']",
            "button.calendar-next",
            "button[aria-label='Forward']",
        ]

        for _ in range(6):
            navigated = False
            for nsel in next_btn_selectors:
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

            if await _try_click(day_selectors):
                return True

        self.logger.debug("calendar_date_not_found", extra={"date": iso})
        return False

    # ---------------------------------------------------------------- #
    # Click *Ver disponibilidad*                                        #
    # ---------------------------------------------------------------- #
    async def _click_ver_disponibilidad(self, page: Page) -> bool:
        # Some pages show a participants picker first
        for sel in (
            "#participantsButton",
            "button:has-text('Continuar')",
            "button:has-text('Continue')",
        ):
            try:
                b = page.locator(sel).first
                if await b.count() > 0 and await b.is_visible():
                    await b.click(timeout=2000)
                    await page.wait_for_timeout(800)
                    break
            except Exception:
                continue

        # Main availability button
        btn_labels = [
            "Ver disponibilidad",
            "Comprueba la disponibilidad",
            "Comprueba disponibilidad",
            "Check availability",
        ]

        clicked = False
        for label in btn_labels:
            loc = page.locator(f"button:has-text('{label}')").first
            try:
                if await loc.count() == 0:
                    continue
                try:
                    if not await loc.is_visible():
                        continue
                except Exception:
                    continue
                try:
                    await loc.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass
                await loc.click(timeout=3000)
                clicked = True
                break
            except Exception:
                # force-click fallback
                try:
                    await page.locator(f"button:has-text('{label}')").first.click(
                        timeout=3000, force=True,
                    )
                    clicked = True
                    break
                except Exception:
                    continue

        # JS fallback
        if not clicked:
            try:
                clicked = await page.evaluate(
                    """() => {
                        for (const el of document.querySelectorAll('button, a')) {
                            const t = (el.innerText || '').toLowerCase();
                            if (
                                t.includes('ver disponibilidad') ||
                                t.includes('comprueba la disponibilidad') ||
                                t.includes('comprueba disponibilidad') ||
                                t.includes('check availability')
                            ) { el.click(); return true; }
                        }
                        return false;
                    }"""
                )
            except Exception:
                clicked = False

        if not clicked:
            self.logger.warning("ver_disponibilidad_not_found")
            return False

        # Wait for availability panel to render
        await page.wait_for_timeout(3000)

        # Participants button may appear *after* Ver disponibilidad
        for sel in ("#participantsButton", "button:has-text('Continuar')"):
            try:
                b = page.locator(sel).first
                if await b.count() > 0 and await b.is_visible():
                    await b.click(timeout=2000)
                    await page.wait_for_timeout(1500)
                    break
            except Exception:
                continue

        # Wait for recognisable panel content
        for sel in (
            "text=opciones disponibles",
            "text=options available",
            "[id^='option-card-']",
            "[data-test-id*='available-option-card']",
            ".activity-option-container",
            "#exposedOptionsContentIdentifierV2",
        ):
            try:
                await page.locator(sel).first.wait_for(timeout=2000)
                return True
            except Exception:
                continue

        await page.wait_for_timeout(1000)

        await self._dismiss_consent_dialogs(page)
        try:
            await page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:
            await page.wait_for_timeout(2000)

        return True

    async def _dismiss_consent_dialogs(self, page: Page) -> None:
        """Cierra banners de cookies / consentimiento que tapen el panel de reserva."""

        labels = (
            "Accept all",
            "Accept All",
            "I agree",
            "Agree",
            "Aceptar todo",
            "Aceptar todas",
            "Aceptar y continuar",
            "Permitir todas",
            "Consentir",
            "OK",
        )
        for label in labels:
            try:
                btn = page.locator(f"button:has-text('{label}')").first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(timeout=2000)
                    await page.wait_for_timeout(500)
                    self.logger.info("consent_dismissed", extra={"label": label})
                    break
            except Exception:
                continue

        for sel in (
            "#onetrust-accept-btn-handler",
            "[data-testid='cookie-accept-all']",
            "button[aria-label*='Accept']",
            "button[aria-label*='aceptar']",
        ):
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=2000)
                    await page.wait_for_timeout(400)
                    self.logger.info("consent_dismissed", extra={"selector": sel})
                    break
            except Exception:
                continue

    async def _scroll_listing_for_lazy_links(self, page: Page) -> None:
        """Fuerza carga de tours enlazados con -t#### en listados con scroll infinito."""

        for i in range(5):
            try:
                await page.evaluate(
                    "() => window.scrollBy(0, Math.floor(window.innerHeight * 0.85))",
                )
                await page.wait_for_timeout(500 + i * 100)
            except Exception:
                break

    # ---------------------------------------------------------------- #
    # Read option cards                                                 #
    # ---------------------------------------------------------------- #
    _CARD_SELS = (
        "[id^='option-card-']",
        "[data-test-id*='available-option-card']",
        "[data-testid*='available-option-card']",
        "[data-testid*='AvailableOption']",
        "[data-test-id='sdui-ba-available-option-card']",
        ".activity-option-container",
        "[class*='available-option-card']",
        "[class*='ActivityOptionCard']",
        "[class*='BookingOption']",
        "[class*='booking-option']",
        "div[class*='OptionCard']",
    )

    async def _read_option_cards(
        self,
        page: Page,
        *,
        page_title: str | None,
    ) -> list[dict]:
        """Read all option cards from the revealed availability panel."""

        raw_cards: list[str] = []
        used_sel: str | None = None

        for sel in self._CARD_SELS:
            try:
                n = await page.locator(sel).count()
                if n == 0:
                    continue
                for i in range(min(n, 15)):
                    try:
                        t = await page.locator(sel).nth(i).inner_text(timeout=2000)
                        if t.strip():
                            raw_cards.append(t.strip())
                    except Exception:
                        continue
                if raw_cards:
                    used_sel = sel
                    break
            except Exception:
                continue

        # Fallback: the whole exposed-options wrapper
        if not raw_cards:
            try:
                sec = page.locator("#exposedOptionsContentIdentifierV2")
                if await sec.count() > 0:
                    t = await sec.inner_text(timeout=3000)
                    if t.strip():
                        raw_cards = [t.strip()]
                        used_sel = "#exposedOptionsContentIdentifierV2"
            except Exception:
                pass

        # Fallback: variantes nuevas de GYG (contenedor genérico con precio)
        if not raw_cards:
            for sel in (
                "[data-testid*='exposed-option']",
                "[id*='exposedOptions']",
                "[class*='ExposedOption']",
            ):
                try:
                    sec = page.locator(sel).first
                    if await sec.count() > 0:
                        t = await sec.inner_text(timeout=3000)
                        if t.strip() and ("€" in t or "EUR" in t.upper()):
                            raw_cards = [t.strip()]
                            used_sel = sel
                            break
                except Exception:
                    continue

        if not raw_cards:
            try:
                cand = page.locator(
                    "main article, [class*='activity-option'], section",
                )
                n = await cand.count()
                for i in range(min(n, 20)):
                    try:
                        t = await cand.nth(i).inner_text(timeout=1500)
                        ts = t.strip()
                        if len(ts) > 30 and "€" in ts:
                            raw_cards.append(ts)
                    except Exception:
                        continue
                if raw_cards:
                    used_sel = "main article / activity-option"
            except Exception:
                pass

        raw_cards = raw_cards[:15]

        self.logger.info(
            "option_cards_raw",
            extra={
                "selector": used_sel,
                "count": len(raw_cards),
                "previews": [c[:150] for c in raw_cards[:5]],
            },
        )

        if not raw_cards:
            try:
                body = await page.inner_text("body")
                self.logger.warning(
                    "no_option_cards",
                    extra={
                        "body_len": len(body),
                        "has_hora": "hora de inicio" in body.lower(),
                        "has_opciones": "opciones disponibles" in body.lower(),
                    },
                )
            except Exception:
                pass
            return []

        # Click each card to reveal hidden content (times, seats)
        enriched_cards = await self._click_cards_and_enrich(page, raw_cards)

        results: list[dict] = []
        for card_text in enriched_cards:
            parsed = self._parse_card(card_text, page_title=page_title)
            if parsed:
                results.append(parsed)
                self.logger.debug(
                    "parsed_card",
                    extra={
                        "name": parsed["option_name"],
                        "slots": [str(s) for s in parsed.get("slot_times", [])],
                        "price": str(parsed.get("price")),
                        "seats": parsed.get("seats_available"),
                        "lang": parsed.get("language_code"),
                    },
                )

        return results

    async def _click_cards_and_enrich(
        self,
        page: Page,
        initial_texts: list[str],
    ) -> list[str]:
        """Click each option card to reveal hidden detail (times, seats).

        GYG option cards only show time-slot buttons AFTER the card is
        selected/expanded.  We click the card, wait for the slots to render
        inside the card DOM, then immediately read ``inner_text`` — BEFORE
        doing anything else that could navigate/change the DOM (e.g. clicking
        "Reservar ahora" opens a checkout flow and hides the time buttons).
        """
        enriched: list[str] = list(initial_texts)

        for sel in self._CARD_SELS:
            try:
                n = await page.locator(sel).count()
            except Exception:
                continue
            if n == 0:
                continue

            for i in range(min(n, 15)):
                card = page.locator(sel).nth(i)

                # ── 1. Click to expand this card ──────────────────────
                try:
                    await card.click(timeout=2000)
                    await page.wait_for_timeout(1500)
                except Exception:
                    pass

                # ── 2. Capture the card text NOW (time-slot buttons are
                #        inside the card DOM once it is selected) ────────
                try:
                    updated = await card.inner_text(timeout=2000)
                    if updated.strip() and i < len(enriched):
                        enriched[i] = updated.strip()
                except Exception:
                    pass

                # ── 3. Close any overlay/modal before the next card ───
                try:
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(400)
                except Exception:
                    pass

            break  # only iterate first matching selector

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
        if norm_name.startswith("barcelona:"):
            norm_name = norm_name.split(":", 1)[1].strip()

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
        for line in lines[:8]:
            low = line.lower()
            if any(low.startswith(p) for p in _NAME_SKIP):
                continue
            if "€" in line or "EUR" in line.upper():
                continue
            if len(line) < 8:
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
        expected = self._expected_phrase(base_url.split("?")[0])

        raw = await page.eval_on_selector_all(
            "a[href]",
            """els => els.map(el => ({
                href: el.getAttribute('href') || '',
                text: (
                    el.closest('article, li, [data-test-id]') || el
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

            if expected:
                norm_text = self._norm(str(item.get("text", "")))
                norm_path = self._norm(
                    path.replace("-", " ").replace("/", " "),
                )
                if expected not in norm_text and expected not in norm_path:
                    continue

            seen.add(absolute)
            urls.append(absolute)

        return urls

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
            detail_page_url = d.get("detail_page_url")
            slots = [
                s for s in d.get("slot_times", []) if isinstance(s, time)
            ] or [None]

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
                            detail_page_url=detail_page_url,
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
                            detail_page_url=detail_page_url,
                        )
                    )

        return prices, avail

    # ---------------------------------------------------------------- #
    # Small helpers                                                     #
    # ---------------------------------------------------------------- #
    @staticmethod
    def _canonical_gyg_product_url(url: str) -> str:
        """Stable tour page URL without query string (date params), for linking."""
        p = urlsplit(url)
        return urlunsplit((p.scheme, p.netloc, p.path, "", ""))

    @staticmethod
    def _url_for_date(source_url: str, target_date: date) -> str:
        p = urlsplit(source_url)
        q = dict(parse_qsl(p.query, keep_blank_values=True))
        d = target_date.isoformat()
        q["date_from"] = d
        q["date_to"] = d
        return urlunsplit(
            (p.scheme, p.netloc, p.path, urlencode(q), p.fragment),
        )

    @staticmethod
    def _expected_phrase(source_url: str) -> str | None:
        path = urlsplit(source_url).path.strip("/")
        if not path:
            return None
        slug = path.split("/")[-1]
        slug = re.sub(r"-l\d+$", "", slug)
        phrase = slug.replace("-", " ").strip()
        return GetYourGuideScraper._norm(phrase) or None

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
        # Replace time ranges (e.g. "12:00 - 12:05") with only the start time so the
        # range endpoint is not mistakenly treated as a separate slot.
        cleaned = _TIME_RANGE_RE.sub(r"\1", text)
        seen: set[time] = set()
        result: list[time] = []
        for h, m in _TIME_RE.findall(cleaned):
            t = time(hour=int(h), minute=int(m))
            if t not in seen:
                seen.add(t)
                result.append(t)
        result.sort()
        return result

    @staticmethod
    def _find_first_price(text: str) -> Decimal | None:
        matches = list(_PRICE_RE.finditer(text))
        if not matches:
            return None
        # Last price token is usually the current/discounted price
        last = matches[-1]
        token = last.group(1) or last.group(2)
        return GetYourGuideScraper._parse_price(token) if token else None

    @staticmethod
    def _find_seats(text: str) -> int | None:
        m = _SEATS_RE.search(text)
        if not m:
            return None
        for g in m.groups():
            if g:
                try:
                    return int(g)
                except ValueError:
                    pass
        return None

    @staticmethod
    def _find_languages(text: str) -> list[str]:
        lowered = GetYourGuideScraper._norm(text)
        found: set[str] = set()
        for term, canonical in _LANG_TERMS.items():
            if term in lowered:
                found.add(canonical)
        return sorted(found)

    @staticmethod
    def _is_unavailable(text: str) -> bool:
        low = text.lower()
        return any(m in low for m in UNAVAILABLE_MARKERS)

    async def _page_h1(self, page: Page) -> str | None:
        try:
            h = await page.locator("h1").first.inner_text(timeout=2000)
            if h and len(h.strip()) >= 8:
                return h.strip()
        except Exception:
            pass
        return None

    async def _fallback_price(self, page: Page) -> Decimal | None:
        """Try JSON-LD or price-selector extraction as last resort."""
        try:
            blocks = await page.eval_on_selector_all(
                "script[type='application/ld+json']",
                "els => els.map(e => e.textContent || '')",
            )
            for b in blocks:
                pr = self._prices_from_jsonld(b)
                if pr:
                    return next(iter(pr.values()))
        except Exception:
            pass

        for sel in ("[data-testid*='price']", "[class*='price']"):
            try:
                vals = await page.eval_on_selector_all(
                    sel,
                    "els => els.map(e => (e.textContent||'').trim()).filter(Boolean)",
                )
                for v in vals:
                    p = self._parse_price(v)
                    if p:
                        return p
            except Exception:
                continue
        return None

    @staticmethod
    def _prices_from_jsonld(block: str) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            return out
        candidates: list[dict] = []
        if isinstance(data, dict):
            o = data.get("offers")
            if isinstance(o, dict):
                candidates.append(o)
            elif isinstance(o, list):
                candidates.extend(i for i in o if isinstance(i, dict))
        for offer in candidates:
            raw = offer.get("price")
            if raw is None:
                continue
            parsed = GetYourGuideScraper._parse_price(str(raw))
            if parsed:
                cur = offer.get("priceCurrency", "EUR")
                out[f"{cur} {raw}"] = parsed
        return out

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

    @staticmethod
    def future_visit_horizons(
        reference_date: date | None = None,
        *,
        start_offset_days: int = 1,
        window_days: int = 14,
    ) -> list[HorizonRequest]:
        """Solo fechas de visita futuras: desde ``today + start_offset_days`` durante ``window_days`` días.

        Por defecto (1, 14): mañana y los siguientes 13 días = dos semanas corridas hacia adelante.
        No incluye días de visita ya pasados respecto a ``reference_date``.
        """
        today = reference_date or datetime.now(UTC).date()
        start_offset_days = max(0, min(180, start_offset_days))
        window_days = max(1, min(181, window_days))
        out: list[HorizonRequest] = []
        for i in range(window_days):
            d = start_offset_days + i
            if d > 180:
                break
            out.append(HorizonRequest(horizon_days=d, target_date=today + timedelta(days=d)))
        return out
