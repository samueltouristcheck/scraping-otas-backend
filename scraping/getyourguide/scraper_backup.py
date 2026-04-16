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
from scraping.getyourguide.selectors import (
    LANGUAGE_KEYWORDS,
    OPTION_KEYWORDS,
    PRICE_SELECTORS,
    SLOT_SELECTORS,
    UNAVAILABLE_MARKERS,
)

_PRICE_REGEX = re.compile(
    r"(?:(?:€|EUR)\s*([0-9]+(?:[.,][0-9]{1,2})?)|([0-9]+(?:[.,][0-9]{1,2})?)\s*(?:€|EUR))",
    re.IGNORECASE,
)
_TIME_REGEX = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_MULTI_SPACE_REGEX = re.compile(r"\s+")
_BOOKED_YESTERDAY_REGEX = re.compile(r"(?:booked|se\s+reserv[oó])\s*(\d+)\s*(?:times\s+yesterday|veces\s+ayer)", re.IGNORECASE)
_TOP_SELLER_REGEX = re.compile(r"(?:ticket\s+m[aá]s\s+vendido|best\s+seller|top\s+pick)", re.IGNORECASE)
_TOP_RATED_REGEX = re.compile(r"(?:mejor\s+valorados|top\s+rated)", re.IGNORECASE)
_BLOCKED_PAGE_REGEX = re.compile(r"(?:ray\s+id|se\s+ha\s+producido\s+un\s+error|access\s+denied|attention\s+required)", re.IGNORECASE)
_SEATS_REGEX = re.compile(r"solo\s+quedan\s+(\d+)\s+plazas?\s+disponibles|solo\s+queda\s+(\d+)\s+plaza\s+disponible", re.IGNORECASE)
_BADGE_MARKERS = {
    "booked",
    "likely to sell out",
    "certified by getyourguide",
    "new activity",
    "provider rating",
    "official ticket",
    "guided tours",
    "skip to main content",
    "ticket más vendido",
    "mejor valorados",
    "se reservó",
}

_CARD_SELECTORS = [
    "article[class*='activity-card']",
    "[data-test-id*='activity-card']",
    "article:has([data-testid*='price'])",
    "li:has([data-testid*='price'])",
]


class GetYourGuideScraper(PlaywrightScraperBase, OtaScraper):
    ota_name = "getyourguide"

    def __init__(self, *, max_retries: int = 3, timeout_ms: int = 30000, headless: bool = True):
        super().__init__(max_retries=max_retries, timeout_ms=timeout_ms, headless=headless)
        self.logger = logging.getLogger("scraping.getyourguide")

    async def scrape(self, source_url: str, horizons: list[HorizonRequest]) -> ScrapeResult:
        captured_at = datetime.now(UTC)
        expected_phrase = self._expected_title_phrase(source_url)
        product_name: str | None = None
        aggregate_languages: set[str] = set()
        aggregate_options: set[str] = set()
        aggregate_slots: set[time] = set()
        all_prices: list[ScrapedPricePoint] = []
        all_availability: list[ScrapedAvailabilityPoint] = []
        raw_excerpt: str | None = None

        try:
            for horizon in horizons:
                target_url = self._url_for_target_date(source_url, horizon.target_date)
                try:
                    page, context = await self.fetch_page(target_url, locale="es-ES", timezone_id="Europe/Madrid")
                except Exception as exc:
                    self.logger.warning(
                        "target_date_scrape_failed",
                        extra={
                            "target_date": horizon.target_date.isoformat(),
                            "horizon_days": horizon.horizon_days,
                            "url": target_url,
                            "error": str(exc),
                        },
                    )
                    continue
                try:
                    if product_name is None:
                        product_name = await page.title()

                    full_text = await page.inner_text("body")
                    if _BLOCKED_PAGE_REGEX.search(full_text):
                        self.logger.warning(
                            "blocked_or_error_page_detected",
                            extra={
                                "target_date": horizon.target_date.isoformat(),
                                "horizon_days": horizon.horizon_days,
                                "url": target_url,
                            },
                        )
                        continue

                    if raw_excerpt is None:
                        raw_excerpt = full_text[:3000]

                    languages = self._extract_languages(full_text)
                    discovered_slots: set[time] = set()
                    option_details = await self._extract_option_details(page, expected_phrase=expected_phrase)
                    if not self._has_option_level_schedule(option_details):
                        merged_option_signals: dict[str, dict[str, object]] = {}
                        detail_urls = await self._extract_detail_urls(
                            page,
                            base_url=target_url,
                            expected_phrase=expected_phrase,
                        )
                        for detail_url in detail_urls[:8]:
                            try:
                                detail_page, detail_context = await self.fetch_page(
                                    self._url_for_target_date(detail_url, horizon.target_date),
                                    locale="es-ES",
                                    timezone_id="Europe/Madrid",
                                )
                            except Exception:
                                self.logger.debug("detail_page_fetch_failed", exc_info=True)
                                continue
                            try:
                                detail_text = await detail_page.inner_text("body")
                                if _BLOCKED_PAGE_REGEX.search(detail_text):
                                    continue
                                detail_option_details = await self._extract_option_details(
                                    detail_page,
                                    expected_phrase=expected_phrase,
                                )
                                detail_slots = await self._extract_slots(detail_page, option_details=detail_option_details)
                                fallback_detail_slots = await self._extract_slots_from_booking_flow(detail_page)
                                if fallback_detail_slots:
                                    merged_detail_slots = set(detail_slots)
                                    merged_detail_slots.update(fallback_detail_slots)
                                    detail_slots = sorted(merged_detail_slots)

                                if detail_option_details and detail_slots:
                                    detail_options_with_slots = [
                                        detail
                                        for detail in detail_option_details
                                        if isinstance(detail.get("slot_times"), list)
                                        and any(isinstance(slot, time) for slot in detail.get("slot_times", []))
                                    ]
                                    detail_options_without_slots = [
                                        detail
                                        for detail in detail_option_details
                                        if not isinstance(detail.get("slot_times"), list)
                                        or not any(isinstance(slot, time) for slot in detail.get("slot_times", []))
                                    ]

                                    detail_assigned_slots: set[time] = set()
                                    for detail in detail_options_with_slots:
                                        detail_slot_values = detail.get("slot_times") if isinstance(detail.get("slot_times"), list) else []
                                        for slot in detail_slot_values:
                                            if isinstance(slot, time):
                                                detail_assigned_slots.add(slot)

                                    detail_remaining_slots = [slot for slot in detail_slots if slot not in detail_assigned_slots]
                                    if len(detail_options_without_slots) == 1 and detail_remaining_slots:
                                        detail_options_without_slots[0]["slot_times"] = detail_remaining_slots

                                if detail_option_details:
                                    for detail in detail_option_details:
                                        option_name = detail.get("option_name")
                                        if not isinstance(option_name, str):
                                            continue
                                        merged_detail = merged_option_signals.setdefault(option_name, {})

                                        slot_times = detail.get("slot_times") if isinstance(detail.get("slot_times"), list) else []
                                        valid_slots = [slot for slot in slot_times if isinstance(slot, time)]
                                        if valid_slots:
                                            existing_slots = merged_detail.get("slot_times") if isinstance(merged_detail.get("slot_times"), list) else []
                                            existing_slot_set = {slot for slot in existing_slots if isinstance(slot, time)}
                                            existing_slot_set.update(valid_slots)
                                            merged_detail["slot_times"] = sorted(existing_slot_set)

                                        seats_available = detail.get("seats_available") if isinstance(detail.get("seats_available"), int) else None
                                        if seats_available is not None and merged_detail.get("seats_available") is None:
                                            merged_detail["seats_available"] = seats_available

                                        language_code = detail.get("language_code") if isinstance(detail.get("language_code"), str) else None
                                        if language_code and merged_detail.get("language_code") is None:
                                            merged_detail["language_code"] = language_code

                                        is_available = detail.get("is_available") if isinstance(detail.get("is_available"), bool) else None
                                        if is_available is not None and merged_detail.get("is_available") is None:
                                            merged_detail["is_available"] = is_available

                                        popularity_count = detail.get("popularity_count_yesterday") if isinstance(detail.get("popularity_count_yesterday"), int) else None
                                        if popularity_count is not None and merged_detail.get("popularity_count_yesterday") is None:
                                            merged_detail["popularity_count_yesterday"] = popularity_count

                                        popularity_label = detail.get("popularity_label") if isinstance(detail.get("popularity_label"), str) else None
                                        if popularity_label and merged_detail.get("popularity_label") is None:
                                            merged_detail["popularity_label"] = popularity_label

                                        price_value = detail.get("price") if isinstance(detail.get("price"), Decimal) else None
                                        if price_value is not None and merged_detail.get("price") is None:
                                            merged_detail["price"] = price_value
                                for slot in detail_slots:
                                    discovered_slots.add(slot)
                            finally:
                                try:
                                    await detail_context.close()
                                except PlaywrightError:
                                    self.logger.debug("detail_context_already_closed", exc_info=True)

                        if merged_option_signals:
                            if option_details:
                                for option_detail in option_details:
                                    option_name = option_detail.get("option_name")
                                    if not isinstance(option_name, str):
                                        continue
                                    merged_detail = merged_option_signals.get(option_name)
                                    if not merged_detail:
                                        continue

                                    merged_slots = merged_detail.get("slot_times") if isinstance(merged_detail.get("slot_times"), list) else []
                                    valid_merged_slots = [slot for slot in merged_slots if isinstance(slot, time)]
                                    if valid_merged_slots:
                                        current_slots = option_detail.get("slot_times") if isinstance(option_detail.get("slot_times"), list) else []
                                        current_slot_set = {slot for slot in current_slots if isinstance(slot, time)}
                                        current_slot_set.update(valid_merged_slots)
                                        option_detail["slot_times"] = sorted(current_slot_set)

                                    if option_detail.get("seats_available") is None and isinstance(merged_detail.get("seats_available"), int):
                                        option_detail["seats_available"] = merged_detail["seats_available"]
                                    if option_detail.get("language_code") is None and isinstance(merged_detail.get("language_code"), str):
                                        option_detail["language_code"] = merged_detail["language_code"]
                                    if option_detail.get("is_available") is None and isinstance(merged_detail.get("is_available"), bool):
                                        option_detail["is_available"] = merged_detail["is_available"]
                                    if option_detail.get("popularity_count_yesterday") is None and isinstance(merged_detail.get("popularity_count_yesterday"), int):
                                        option_detail["popularity_count_yesterday"] = merged_detail["popularity_count_yesterday"]
                                    if option_detail.get("popularity_label") is None and isinstance(merged_detail.get("popularity_label"), str):
                                        option_detail["popularity_label"] = merged_detail["popularity_label"]
                                    if option_detail.get("price") is None and isinstance(merged_detail.get("price"), Decimal):
                                        option_detail["price"] = merged_detail["price"]
                            else:
                                option_details = [
                                    {
                                        "option_name": option_name,
                                        "slot_times": merged_detail.get("slot_times", []),
                                        "seats_available": merged_detail.get("seats_available"),
                                        "language_code": merged_detail.get("language_code"),
                                        "is_available": merged_detail.get("is_available") if isinstance(merged_detail.get("is_available"), bool) else True,
                                        "popularity_count_yesterday": merged_detail.get("popularity_count_yesterday"),
                                        "popularity_label": merged_detail.get("popularity_label"),
                                        "price": merged_detail.get("price"),
                                    }
                                    for option_name, merged_detail in merged_option_signals.items()
                                ]

                    option_price_map, option_popularity_map, option_popularity_label_map = await self._extract_option_signals(
                        page,
                        expected_phrase=expected_phrase,
                    )
                    options = list({detail["option_name"] for detail in option_details}) or list(option_price_map.keys()) or self._extract_options(full_text)
                    slots = await self._extract_slots(page, option_details=option_details)
                    if not slots:
                        if discovered_slots:
                            slots = sorted(discovered_slots)
                    fallback_slots = await self._extract_slots_from_booking_flow(page)
                    if fallback_slots:
                        merged_slots = set(slots)
                        merged_slots.update(fallback_slots)
                        slots = sorted(merged_slots)

                    if option_details and slots:
                        options_with_slots = [
                            detail
                            for detail in option_details
                            if isinstance(detail.get("slot_times"), list)
                            and any(isinstance(slot, time) for slot in detail.get("slot_times", []))
                        ]
                        options_without_slots = [
                            detail
                            for detail in option_details
                            if not isinstance(detail.get("slot_times"), list)
                            or not any(isinstance(slot, time) for slot in detail.get("slot_times", []))
                        ]
                        assigned_slots: set[time] = set()
                        for detail in options_with_slots:
                            detail_slots = detail.get("slot_times") if isinstance(detail.get("slot_times"), list) else []
                            for slot in detail_slots:
                                if isinstance(slot, time):
                                    assigned_slots.add(slot)

                        remaining_slots = [slot for slot in slots if slot not in assigned_slots]
                        if len(options_without_slots) == 1 and remaining_slots:
                            options_without_slots[0]["slot_times"] = remaining_slots
                    prices_map = await self._extract_prices(page)
                    unavailable = self._is_unavailable(full_text)

                    aggregate_languages.update(languages)
                    aggregate_options.update(options)
                    aggregate_slots.update(slots)

                    horizon_prices = self._price_points_for_horizon(
                        target_date=horizon.target_date,
                        horizon_days=horizon.horizon_days,
                        observed_at=captured_at,
                        prices=prices_map,
                        option_price_map=option_price_map,
                        option_popularity_map=option_popularity_map,
                        option_popularity_label_map=option_popularity_label_map,
                        option_details=option_details,
                        slots=slots,
                        languages=languages,
                        options=options,
                    )
                    all_prices.extend(horizon_prices)

                    availability_points = self._availability_points_for_horizon(
                        target_date=horizon.target_date,
                        horizon_days=horizon.horizon_days,
                        observed_at=captured_at,
                        option_details=option_details,
                        slots=slots,
                        languages=languages,
                        options=options,
                        unavailable=unavailable,
                    )
                    all_availability.extend(availability_points)
                finally:
                    try:
                        await context.close()
                    except PlaywrightError:
                        self.logger.debug("context_already_closed", exc_info=True)

            return ScrapeResult(
                ota_name=self.ota_name,
                source_url=source_url,
                product_name=product_name,
                captured_at=captured_at,
                languages=sorted(aggregate_languages),
                options=sorted(aggregate_options),
                slots=sorted(aggregate_slots),
                prices=all_prices,
                availability=all_availability,
                raw_excerpt=raw_excerpt,
            )
        finally:
            await self.close()

    @staticmethod
    def _url_for_target_date(source_url: str, target_date: date) -> str:
        parsed = urlsplit(source_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        date_value = target_date.isoformat()
        query["date_from"] = date_value
        query["date_to"] = date_value
        updated_query = urlencode(query)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, updated_query, parsed.fragment))

    async def _extract_option_signals(
        self,
        page: Page,
        *,
        expected_phrase: str | None,
    ) -> tuple[dict[str, Decimal], dict[str, int], dict[str, str]]:
        card_blocks = await self._extract_card_blocks(page)

        option_prices: dict[str, Decimal] = {}
        option_popularity_counts: dict[str, int] = {}
        option_popularity_labels: dict[str, str] = {}
        for block in card_blocks:
            parsed = self._parse_card_block(block, expected_phrase=expected_phrase)
            if parsed is None:
                continue
            option_name, price, popularity_count, popularity_label = parsed
            if option_name not in option_prices:
                option_prices[option_name] = price
            if popularity_count is not None:
                existing_count = option_popularity_counts.get(option_name)
                if existing_count is None or popularity_count > existing_count:
                    option_popularity_counts[option_name] = popularity_count
            if popularity_label is not None:
                option_popularity_labels[option_name] = popularity_label

        return option_prices, option_popularity_counts, option_popularity_labels

    async def _extract_detail_urls(self, page: Page, *, base_url: str, expected_phrase: str | None) -> list[str]:
        link_candidates = await page.eval_on_selector_all(
            "article[class*='activity-card'], [data-test-id*='activity-card'], li:has(a[href])",
            """
            elements => elements.map(el => {
              const anchor = el.querySelector('a[href]');
              const titleNode = el.querySelector('.title, h1, h2, h3, [class*=title]');
              return {
                href: anchor ? anchor.getAttribute('href') : '',
                title: (titleNode?.textContent || '').trim(),
                text: (el.innerText || '').trim()
              };
            }).filter(item => item.href)
            """,
        )

        selected: list[str] = []
        seen: set[str] = set()
        for item in link_candidates:
            href = str(item.get("href") or "").strip()
            if not href:
                continue

            title = str(item.get("title") or "")
            card_text = str(item.get("text") or "")
            candidate_text = title or card_text
            if expected_phrase and expected_phrase not in self._normalize_text(candidate_text):
                continue

            absolute_url = urljoin(base_url, href)
            normalized_url = absolute_url.split("#", 1)[0]
            if normalized_url in seen:
                continue
            seen.add(normalized_url)
            selected.append(normalized_url)

        return selected

    async def _extract_option_details(self, page: Page, *, expected_phrase: str | None) -> list[dict[str, object]]:
        await self._open_booking_options(page)

        relax_expected_phrase = False
        if expected_phrase:
            try:
                page_context = await page.eval_on_selector_all(
                    "h1, title, main, #main-content-wrapper",
                    "elements => elements.map(e => (e.textContent || '').trim()).join(' | ')",
                )
                normalized_context = self._normalize_text(page_context or "")
                relax_expected_phrase = expected_phrase in normalized_context
            except Exception:
                relax_expected_phrase = False

        try:
            await page.eval_on_selector_all(
                "details.activity-option-wrapper",
                "elements => elements.forEach(el => el.setAttribute('open', ''))",
            )
        except PlaywrightError:
            self.logger.debug("failed_to_expand_option_cards", exc_info=True)

        card_payloads = await page.eval_on_selector_all(
                        "[data-test-id='sdui-ba-available-option-card'], [data-test-id*='available-option-card'], [id^='option-card-'], .activity-option-container, [class*='available-option-card']",
            """
            elements => elements.map(el => ({
                            title: (el.querySelector('.title, h1, h2, h3, [class*=title]')?.textContent || '').trim(),
              text: (el.innerText || '').trim(),
              priceText: (el.querySelector('.activity-option-price-wrapper__price')?.textContent || '').trim(),
              badgeText: (el.querySelector('.badge-label')?.textContent || '').trim(),
              languageText: Array.from(el.querySelectorAll('.inclusion-label')).map(node => (node.textContent || '').trim()).join(' | '),
                            timeText: Array.from(el.querySelectorAll('.starting-times__container, .starting-times__layout, [data-testid*=timeslot], [class*=timeslot], [class*=time-slot]')).map(node => (node.innerText || '').trim()).join(' | '),
                            buttonTimeText: Array.from(el.querySelectorAll('button')).map(node => (node.textContent || '').trim()).filter(text => /\\b([01]?\\d|2[0-3]):([0-5]\\d)\\b/.test(text)).join(' | ')
            }))
            """,
        )

        details: list[dict[str, object]] = []
        for payload in card_payloads:
            title = str(payload.get("title") or "").strip()
            block_text = str(payload.get("text") or "").strip()
            if not title and block_text:
                first_lines = [line.strip() for line in block_text.splitlines() if line.strip()]
                title = first_lines[0] if first_lines else ""

            if not title or not block_text:
                continue

            normalized_title = self._normalize_text(title)
            if normalized_title.startswith("barcelona:"):
                normalized_title = normalized_title.split(":", 1)[1].strip()
            if expected_phrase and not relax_expected_phrase and expected_phrase not in normalized_title:
                continue

            price_text = str(payload.get("priceText") or "")
            parsed_price = self._parse_price(price_text) if price_text else None
            if parsed_price is None:
                parsed = self._parse_card_block(block_text, expected_phrase=expected_phrase)
                if parsed is not None:
                    _, parsed_price, _, _ = parsed

            seats_available = self._extract_seats_available(str(payload.get("badgeText") or ""), block_text)
            slot_times = self._extract_slot_times(
                f"{payload.get('timeText') or ''} | {payload.get('buttonTimeText') or ''}",
                block_text,
            )

            language_text = f"{payload.get('languageText') or ''} {block_text}"
            languages = self._extract_languages(language_text)
            language_code = languages[0] if languages else None

            popularity_count = None
            popularity_label = None
            popularity_match = _BOOKED_YESTERDAY_REGEX.search(block_text)
            if popularity_match:
                try:
                    popularity_count = int(popularity_match.group(1))
                except ValueError:
                    popularity_count = None
            if popularity_count is not None:
                popularity_label = self._popularity_label(popularity_count)
            elif _TOP_SELLER_REGEX.search(block_text):
                popularity_label = "popular"
            elif _TOP_RATED_REGEX.search(block_text):
                popularity_label = "featured"

            details.append(
                {
                    "option_name": normalized_title,
                    "price": parsed_price,
                    "slot_times": slot_times,
                    "language_code": language_code,
                    "is_available": not self._is_unavailable(block_text),
                    "seats_available": seats_available,
                    "popularity_count_yesterday": popularity_count,
                    "popularity_label": popularity_label,
                }
            )

        if details and not self._has_option_level_schedule(details):
            await self._enrich_option_details_with_select_flow(page, details)

        return details

    async def _enrich_option_details_with_select_flow(self, page: Page, details: list[dict[str, object]]) -> None:
        card_selector = "[id^='option-card-'], .activity-option-container, [data-test-id='sdui-ba-available-option-card'], [data-test-id*='available-option-card']"
        card_count = await page.locator(card_selector).count()
        if card_count <= 0:
            return

        max_cards = min(card_count, 20)
        for idx in range(max_cards):
            card = page.locator(card_selector).nth(idx)
            try:
                title_text = (
                    await card.locator(".title, h1, h2, h3, [class*=title]").first.inner_text(timeout=1200)
                ).strip()
            except Exception:
                title_text = ""

            try:
                await card.click(timeout=1800)
                await page.wait_for_timeout(700)
            except Exception:
                pass

            try:
                card_text = (await card.inner_text(timeout=1600)).strip()
            except Exception:
                card_text = ""

            try:
                card_slot_text = await card.evaluate(
                    """
                    el => Array.from(el.querySelectorAll('button, [data-testid*=timeslot], [class*=timeslot], [class*=time-slot]'))
                        .map(node => (node.textContent || '').trim())
                        .filter(Boolean)
                        .join(' | ')
                    """
                )
            except Exception:
                card_slot_text = ""

            parsed_slots = self._extract_slot_times(card_slot_text, card_text)
            seats_available = self._extract_seats_available("", card_text)

            try:
                select_button = card.locator(
                    "button:has-text('Seleccionar'), #select-option-button, button:has-text('Reservar ahora'), button:has-text('Añadir al carrito')"
                ).first
                if await select_button.count() == 0:
                    raise PlaywrightError("option_select_button_missing")
                await select_button.click(timeout=2500)
                await page.wait_for_timeout(1200)
            except Exception:
                pass

            body_text = await page.inner_text("body")
            if not parsed_slots:
                parsed_slots = self._extract_slot_times(body_text, "")
            if seats_available is None:
                seats_available = self._extract_seats_available("", body_text)

            normalized_title = self._normalize_text(title_text) if title_text else ""
            target_detail = None
            for detail in details:
                option_name = detail.get("option_name")
                if not isinstance(option_name, str):
                    continue
                if normalized_title and (normalized_title in option_name or option_name in normalized_title):
                    target_detail = detail
                    break

            if target_detail is None and card_text:
                first_lines = [line.strip() for line in card_text.splitlines() if line.strip()]
                if first_lines:
                    normalized_first_line = self._normalize_text(first_lines[0])
                    for detail in details:
                        option_name = detail.get("option_name")
                        if not isinstance(option_name, str):
                            continue
                        if normalized_first_line in option_name or option_name in normalized_first_line:
                            target_detail = detail
                            break

            if target_detail is None and parsed_slots:
                candidate_text = normalized_title
                if not candidate_text and card_text:
                    first_lines = [line.strip() for line in card_text.splitlines() if line.strip()]
                    if first_lines:
                        candidate_text = self._normalize_text(first_lines[0])

                if candidate_text:
                    candidate_tokens = {token for token in candidate_text.split() if len(token) >= 4}
                    best_overlap = 0
                    best_detail: dict[str, object] | None = None
                    for detail in details:
                        option_name = detail.get("option_name")
                        if not isinstance(option_name, str):
                            continue
                        detail_tokens = {token for token in option_name.split() if len(token) >= 4}
                        overlap = len(candidate_tokens & detail_tokens)
                        if overlap > best_overlap:
                            best_overlap = overlap
                            best_detail = detail

                    if best_detail is not None and best_overlap >= 2:
                        target_detail = best_detail

            if target_detail is not None and parsed_slots:
                target_detail["slot_times"] = parsed_slots
            if target_detail is not None and seats_available is not None and target_detail.get("seats_available") is None:
                target_detail["seats_available"] = seats_available

            try:
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(300)
            except Exception:
                pass

    async def _open_booking_options(self, page: Page) -> None:
        participant_continue_selectors = [
            "#participantsButton",
            "button:has-text('Continuar')",
            "button:has-text('Continue')",
        ]
        for selector in participant_continue_selectors:
            try:
                participant_button = page.locator(selector).first
                if await participant_button.count() == 0:
                    continue
                await participant_button.click(timeout=1600)
                await page.wait_for_timeout(500)
                break
            except Exception:
                continue

        selectors = [
            "button.js-check-availability",
            "button:has-text('Ver disponibilidad')",
            "button:has-text('Comprueba la disponibilidad')",
            "button:has-text('Comprueba disponibilidad')",
            "button:has-text('Check availability')",
            "button:has-text('Reservar ahora')",
            "button:has-text('Book now')",
            "a:has-text('Comprueba la disponibilidad')",
            "a:has-text('Check availability')",
        ]

        clicked = False
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = await locator.count()
            except Exception:
                count = 0
            if count == 0:
                continue

            for idx in range(min(count, 4)):
                candidate = locator.nth(idx)
                try:
                    if not await candidate.is_visible():
                        continue
                except Exception:
                    continue

                try:
                    await candidate.scroll_into_view_if_needed(timeout=1200)
                except Exception:
                    pass

                clicked_current = False
                try:
                    await candidate.click(timeout=2500)
                    clicked_current = True
                except Exception:
                    try:
                        await candidate.click(timeout=2500, force=True)
                        clicked_current = True
                    except Exception:
                        try:
                            await candidate.evaluate("el => el.click()")
                            clicked_current = True
                        except Exception:
                            clicked_current = False

                if not clicked_current:
                    continue

                await page.wait_for_timeout(1800)
                clicked = True
                break

            if clicked:
                break

        if not clicked:
            js_clicked = False
            try:
                js_clicked = await page.evaluate(
                    """
                    () => {
                      const selectors = [
                        'button.js-check-availability',
                        'button[data-test-id="activity-price-info"] .js-check-availability',
                        'button'
                      ];
                      const isAvailabilityButton = (el) => {
                        if (!el) return false;
                        const text = (el.innerText || el.textContent || '').toLowerCase();
                        return text.includes('ver disponibilidad') || text.includes('comprueba la disponibilidad') || text.includes('check availability');
                      };
                      for (const selector of selectors) {
                        const nodes = Array.from(document.querySelectorAll(selector));
                        for (const node of nodes) {
                          if (selector === 'button' && !isAvailabilityButton(node)) continue;
                          if (selector !== 'button' && !isAvailabilityButton(node) && selector !== 'button.js-check-availability') continue;
                          node.click();
                          return true;
                        }
                      }
                      return false;
                    }
                    """
                )
            except Exception:
                js_clicked = False

            if js_clicked:
                clicked = True
                try:
                    await page.wait_for_timeout(2200)
                except PlaywrightError:
                    self.logger.debug("booking_options_wait_after_js_click_failed", exc_info=True)

        for selector in participant_continue_selectors:
            try:
                participant_button = page.locator(selector).first
                if await participant_button.count() == 0:
                    continue
                await participant_button.click(timeout=1600)
                await page.wait_for_timeout(500)
                break
            except Exception:
                continue

        if not clicked:
            role_candidates = [
                r"ver disponibilidad",
                r"comprueba(?:\s+la)?\s+disponibilidad",
                r"check availability",
            ]
            for candidate in role_candidates:
                try:
                    role_button = page.get_by_role("button", name=re.compile(candidate, re.IGNORECASE)).first
                    if await role_button.count() == 0:
                        continue
                    try:
                        await role_button.click(timeout=2500)
                    except Exception:
                        await role_button.click(timeout=2500, force=True)
                    await page.wait_for_timeout(2200)
                    clicked = True
                    break
                except Exception:
                    continue

        reveal_selectors = [
            "[data-test-id='sdui-ba-available-option-card']",
            "[id^='option-card-']",
            ".activity-option-container",
            ".starting-times__container",
            ".starting-times__layout",
        ]
        for reveal_selector in reveal_selectors:
            try:
                await page.locator(reveal_selector).first.wait_for(timeout=3000)
                return
            except Exception:
                continue

        try:
            await page.locator("#exposedOptionsContentIdentifierV2").first.wait_for(timeout=3000)
        except Exception:
            try:
                await page.wait_for_timeout(1500)
            except PlaywrightError:
                self.logger.debug("booking_options_wait_failed", exc_info=True)

    @staticmethod
    def _extract_slot_times(primary_text: str, fallback_text: str) -> list[time]:
        slots: set[time] = set()
        for source_text in (primary_text, fallback_text):
            for hour_str, minute_str in _TIME_REGEX.findall(source_text):
                slots.add(time(hour=int(hour_str), minute=int(minute_str)))
        return sorted(slots)

    @staticmethod
    def _has_option_level_schedule(option_details: list[dict[str, object]]) -> bool:
        for detail in option_details:
            slot_times = detail.get("slot_times")
            if isinstance(slot_times, list) and any(isinstance(slot, time) for slot in slot_times):
                return True
        return False

    @staticmethod
    def _extract_seats_available(badge_text: str, fallback_text: str) -> int | None:
        for source_text in (badge_text, fallback_text):
            match = _SEATS_REGEX.search(source_text)
            if not match:
                continue
            for group in match.groups():
                if group is None:
                    continue
                try:
                    return int(group)
                except ValueError:
                    continue
        return None

    async def _extract_card_blocks(self, page: Page) -> list[str]:
        seen: set[str] = set()
        card_blocks: list[str] = []

        for selector in _CARD_SELECTORS:
            blocks = await page.eval_on_selector_all(
                selector,
                """
                elements => elements
                  .map(e => (e.innerText || '').trim())
                  .filter(Boolean)
                """,
            )
            for block in blocks:
                block_text = block.strip()
                normalized_key = _MULTI_SPACE_REGEX.sub(" ", block_text)
                if not block_text or normalized_key in seen:
                    continue
                if "€" not in block_text and "EUR" not in block_text:
                    continue
                seen.add(normalized_key)
                card_blocks.append(block_text)

        if card_blocks:
            return card_blocks

        fallback_blocks = await page.eval_on_selector_all(
            "article, li, div",
            """
            elements => elements
              .map(e => (e.innerText || '').trim())
              .filter(t => t.includes('EUR') || t.includes('€'))
            """,
        )
        return [_MULTI_SPACE_REGEX.sub(" ", block).strip() for block in fallback_blocks if block.strip()]

    @staticmethod
    def _extract_price_tokens(raw_text: str) -> list[str]:
        tokens: list[str] = []
        for match in _PRICE_REGEX.finditer(raw_text):
            token = match.group(1) or match.group(2)
            if token:
                tokens.append(token)
        return tokens

    @staticmethod
    def _parse_card_block(
        block_text: str,
        *,
        expected_phrase: str | None,
    ) -> tuple[str, Decimal, int | None, str | None] | None:
        lines = [line.strip() for line in block_text.splitlines() if line.strip()]
        if len(lines) < 2:
            return None

        title_candidates = [
            line
            for line in lines[:8]
            if not line.lower().startswith("desde")
            and "eur" not in line.lower()
            and "€" not in line
            and len(line) >= 12
        ]
        if not title_candidates:
            return None

        preferred_title = next(
            (
                line
                for line in title_candidates
                if ":" in line and ("sagrada" in line.lower() or "barcelona" in line.lower())
            ),
            None,
        )
        if preferred_title is None:
            preferred_title = next(
                (line for line in title_candidates if "sagrada" in line.lower() or "barcelona" in line.lower()),
                title_candidates[0],
            )

        title = _MULTI_SPACE_REGEX.sub(" ", preferred_title).strip(" -•")
        if title.lower().startswith("barcelona:"):
            title = title.split(":", 1)[1].strip()

        if len(title) < 8:
            return None

        if expected_phrase and expected_phrase not in GetYourGuideScraper._normalize_text(title):
            return None

        lowered_title = title.lower()
        if any(marker in lowered_title for marker in _BADGE_MARKERS):
            return None

        price_matches = GetYourGuideScraper._extract_price_tokens(block_text)
        if not price_matches:
            return None

        parsed_price = GetYourGuideScraper._parse_price(price_matches[-1])
        if parsed_price is None:
            return None

        popularity_count = None
        popularity_label = None
        popularity_match = _BOOKED_YESTERDAY_REGEX.search(block_text)
        if popularity_match:
            try:
                popularity_count = int(popularity_match.group(1))
            except ValueError:
                popularity_count = None
        if popularity_count is not None:
            popularity_label = GetYourGuideScraper._popularity_label(popularity_count)
        elif _TOP_SELLER_REGEX.search(block_text):
            popularity_label = "popular"
        elif _TOP_RATED_REGEX.search(block_text):
            popularity_label = "featured"

        return title.lower(), parsed_price, popularity_count, popularity_label

    @staticmethod
    def _normalize_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        stripped = "".join(char for char in normalized if not unicodedata.combining(char))
        compact = _MULTI_SPACE_REGEX.sub(" ", stripped).strip().lower()
        return compact

    @staticmethod
    def _expected_title_phrase(source_url: str) -> str | None:
        path = urlsplit(source_url).path.strip("/")
        if not path:
            return None

        slug = path.split("/")[-1]
        slug = re.sub(r"-l\d+$", "", slug)
        phrase = slug.replace("-", " ").strip()
        phrase = GetYourGuideScraper._normalize_text(phrase)
        return phrase or None

    @staticmethod
    def _popularity_label(popularity_count: int | None) -> str | None:
        if popularity_count is None:
            return None
        if popularity_count >= 50:
            return "very-popular"
        if popularity_count >= 30:
            return "popular"
        if popularity_count >= 10:
            return "booked"
        return "emerging"

    @staticmethod
    def default_horizons(reference_date: date | None = None, daily_window_days: int = 7) -> list[HorizonRequest]:
        today = reference_date or datetime.now(UTC).date()
        bounded_daily_window = max(0, min(180, daily_window_days))
        horizon_days_set = set(range(0, bounded_daily_window + 1))

        return [
            HorizonRequest(horizon_days=days, target_date=today + timedelta(days=days))
            for days in sorted(horizon_days_set)
        ]

    async def _extract_prices(self, page: Page) -> dict[str, Decimal]:
        prices: dict[str, Decimal] = {}

        for selector in PRICE_SELECTORS:
            values = await page.eval_on_selector_all(
                selector,
                "elements => elements.map(e => (e.textContent || '').trim()).filter(Boolean)",
            )
            for value in values:
                parsed = self._parse_price(value)
                if parsed is not None:
                    prices[value] = parsed

        json_ld_blocks = await page.eval_on_selector_all(
            "script[type='application/ld+json']",
            "elements => elements.map(e => e.textContent || '')",
        )
        for block in json_ld_blocks:
            prices.update(self._extract_prices_from_jsonld(block))

        if not prices:
            body_text = await page.inner_text("body")
            for match in self._extract_price_tokens(body_text):
                parsed = self._parse_price(match)
                if parsed is not None:
                    prices[f"EUR {match}"] = parsed

        return prices

    @staticmethod
    def _extract_prices_from_jsonld(block: str) -> dict[str, Decimal]:
        extracted: dict[str, Decimal] = {}
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            return extracted

        candidates: list[dict] = []
        if isinstance(payload, dict):
            offers = payload.get("offers")
            if isinstance(offers, dict):
                candidates.append(offers)
            elif isinstance(offers, list):
                candidates.extend(item for item in offers if isinstance(item, dict))

        for offer in candidates:
            price_raw = offer.get("price")
            if price_raw is None:
                continue
            parsed = GetYourGuideScraper._parse_price(str(price_raw))
            if parsed is not None:
                currency = offer.get("priceCurrency", "EUR")
                extracted[f"{currency} {price_raw}"] = parsed
        return extracted

    async def _extract_slots(self, page: Page, *, option_details: list[dict[str, object]] | None = None) -> list[time]:
        if option_details:
            slots: set[time] = set()
            for detail in option_details:
                for slot in detail.get("slot_times", []):
                    if isinstance(slot, time):
                        slots.add(slot)
            if slots:
                return sorted(slots)

        text_values: list[str] = []
        for selector in SLOT_SELECTORS:
            values = await page.eval_on_selector_all(
                selector,
                "elements => elements.map(e => (e.textContent || '').trim()).filter(Boolean)",
            )
            text_values.extend(values)

        body_text = await page.inner_text("body")
        text_values.append(body_text)

        slots: set[time] = set()
        for text_value in text_values:
            for hour_str, minute_str in _TIME_REGEX.findall(text_value):
                slots.add(time(hour=int(hour_str), minute=int(minute_str)))

        return sorted(slots)

    async def _extract_slots_from_booking_flow(self, page: Page) -> list[time]:
        await self._open_booking_options(page)

        collected_slots: set[time] = set()
        try:
            initial_slot_text = await page.eval_on_selector_all(
                ".starting-times__container button, .starting-times__layout button, [data-testid*='timeslot'], [class*='timeslot'], [class*='time-slot']",
                "elements => elements.map(e => (e.textContent || '').trim()).filter(Boolean).join(' | ')",
            )
            initial_body_text = await page.inner_text("body")
            for slot in self._extract_slot_times(initial_slot_text, initial_body_text):
                collected_slots.add(slot)
        except Exception:
            pass

        triggers = [
            "button:has-text('Seleccionar')",
            "#select-option-button",
            "button:has-text('Reservar ahora')",
            "button:has-text('Añadir al carrito')",
            "button:has-text('Book now')",
        ]

        for selector in triggers:
            count = 0
            try:
                count = await page.locator(selector).count()
            except Exception:
                count = 0

            for idx in range(min(count, 4)):
                trigger = page.locator(selector).nth(idx)
                try:
                    await trigger.click(timeout=2500)
                    await page.wait_for_timeout(1200)
                    slot_text = await page.eval_on_selector_all(
                        ".starting-times__container button, .starting-times__layout button, [data-testid*='timeslot'], [class*='timeslot'], [class*='time-slot']",
                        "elements => elements.map(e => (e.textContent || '').trim()).filter(Boolean).join(' | ')",
                    )
                    body_text = await page.inner_text("body")
                    parsed_slots = self._extract_slot_times(slot_text, body_text)
                    for slot in parsed_slots:
                        collected_slots.add(slot)
                except Exception:
                    continue

        return sorted(collected_slots)[:20]

    @staticmethod
    def _extract_languages(full_text: str) -> list[str]:
        lowered = full_text.lower()
        found = [lang for lang in LANGUAGE_KEYWORDS if lang in lowered]
        return sorted(set(found))

    @staticmethod
    def _extract_options(full_text: str) -> list[str]:
        lowered = full_text.lower()
        found = [opt for opt in OPTION_KEYWORDS if opt in lowered]
        return sorted(set(found))

    @staticmethod
    def _is_unavailable(full_text: str) -> bool:
        lowered = full_text.lower()
        return any(marker in lowered for marker in UNAVAILABLE_MARKERS)

    @staticmethod
    def _parse_price(raw_value: str) -> Decimal | None:
        tokens = GetYourGuideScraper._extract_price_tokens(raw_value)
        if tokens:
            normalized = tokens[0].replace(",", ".")
        else:
            compact = raw_value.strip().replace("\u00a0", " ").replace(" ", "")
            if not re.fullmatch(r"[0-9]+(?:[.,][0-9]{1,2})?", compact):
                return None
            normalized = compact.replace(",", ".")

        try:
            return Decimal(normalized)
        except ArithmeticError:
            return None

    @staticmethod
    def _price_points_for_horizon(
        *,
        target_date: date,
        horizon_days: int,
        observed_at: datetime,
        prices: dict[str, Decimal],
        option_price_map: dict[str, Decimal],
        option_popularity_map: dict[str, int],
        option_popularity_label_map: dict[str, str],
        option_details: list[dict[str, object]],
        slots: list[time],
        languages: list[str],
        options: list[str],
    ) -> list[ScrapedPricePoint]:
        if option_details:
            points: list[ScrapedPricePoint] = []
            seen_keys: set[tuple[str | None, time | None, str | None]] = set()
            fallback_price = next(iter(option_price_map.values()), None) or next(iter(prices.values()), None)
            for detail in option_details:
                option_name = detail.get("option_name") if isinstance(detail.get("option_name"), str) else None
                option_price = detail.get("price") if isinstance(detail.get("price"), Decimal) else fallback_price
                if option_price is None:
                    continue

                slot_candidates = detail.get("slot_times") if isinstance(detail.get("slot_times"), list) else []
                slot_candidates = [slot for slot in slot_candidates if isinstance(slot, time)] or [None]
                language_code = detail.get("language_code") if isinstance(detail.get("language_code"), str) else None
                popularity_count = detail.get("popularity_count_yesterday") if isinstance(detail.get("popularity_count_yesterday"), int) else None
                popularity_label = detail.get("popularity_label") if isinstance(detail.get("popularity_label"), str) else None
                if popularity_label is None:
                    popularity_label = GetYourGuideScraper._popularity_label(popularity_count)

                for slot in slot_candidates:
                    key = (option_name, slot, language_code)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    points.append(
                        ScrapedPricePoint(
                            target_date=target_date,
                            horizon_days=horizon_days,
                            observed_at=observed_at,
                            slot_time=slot,
                            language_code=language_code,
                            option_name=option_name,
                            currency_code="EUR",
                            list_price=option_price,
                            final_price=option_price,
                            popularity_count_yesterday=popularity_count,
                            popularity_label=popularity_label,
                        )
                    )
            if points:
                return points

        if not prices and not option_price_map:
            return []

        fallback_price = next(iter(option_price_map.values()), None)
        if fallback_price is None:
            fallback_price = next(iter(prices.values()), None)
        if fallback_price is None:
            return []

        slot_candidates = slots or [None]
        language_candidates = languages or [None]
        option_candidates = options or [None]

        points: list[ScrapedPricePoint] = []
        for slot in slot_candidates:
            for language in language_candidates:
                for option in option_candidates:
                    option_key = option.lower().strip() if isinstance(option, str) else ""
                    option_price = option_price_map.get(option_key, fallback_price)
                    popularity_count = option_popularity_map.get(option_key)
                    popularity_label = option_popularity_label_map.get(option_key)
                    if popularity_label is None:
                        popularity_label = GetYourGuideScraper._popularity_label(popularity_count)
                    points.append(
                        ScrapedPricePoint(
                            target_date=target_date,
                            horizon_days=horizon_days,
                            observed_at=observed_at,
                            slot_time=slot,
                            language_code=language,
                            option_name=option,
                            currency_code="EUR",
                            list_price=option_price,
                            final_price=option_price,
                            popularity_count_yesterday=popularity_count,
                            popularity_label=popularity_label,
                        )
                    )
        return points

    @staticmethod
    def _availability_points_for_horizon(
        *,
        target_date: date,
        horizon_days: int,
        observed_at: datetime,
        option_details: list[dict[str, object]],
        slots: list[time],
        languages: list[str],
        options: list[str],
        unavailable: bool,
    ) -> list[ScrapedAvailabilityPoint]:
        if option_details:
            points: list[ScrapedAvailabilityPoint] = []
            seen_keys: set[tuple[str | None, time | None, str | None]] = set()
            for detail in option_details:
                option_name = detail.get("option_name") if isinstance(detail.get("option_name"), str) else None
                slot_candidates = detail.get("slot_times") if isinstance(detail.get("slot_times"), list) else []
                slot_candidates = [slot for slot in slot_candidates if isinstance(slot, time)] or [None]
                language_code = detail.get("language_code") if isinstance(detail.get("language_code"), str) else None
                is_available = detail.get("is_available") if isinstance(detail.get("is_available"), bool) else (not unavailable)
                seats_available = detail.get("seats_available") if isinstance(detail.get("seats_available"), int) else None

                for slot in slot_candidates:
                    key = (option_name, slot, language_code)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    points.append(
                        ScrapedAvailabilityPoint(
                            target_date=target_date,
                            horizon_days=horizon_days,
                            observed_at=observed_at,
                            slot_time=slot,
                            language_code=language_code,
                            option_name=option_name,
                            is_available=is_available,
                            seats_available=seats_available,
                        )
                    )
            if points:
                return points

        slot_candidates = slots or [None]
        language_candidates = languages or [None]
        option_candidates = options or [None]

        points: list[ScrapedAvailabilityPoint] = []
        for slot in slot_candidates:
            for language in language_candidates:
                for option in option_candidates:
                    points.append(
                        ScrapedAvailabilityPoint(
                            target_date=target_date,
                            horizon_days=horizon_days,
                            observed_at=observed_at,
                            slot_time=slot,
                            language_code=language,
                            option_name=option,
                            is_available=not unavailable,
                            seats_available=None,
                        )
                    )
        return points
