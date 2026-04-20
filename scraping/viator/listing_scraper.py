"""Viator listing-page scraper.

Stays on the search-results grid and captures every tour card:
  - Tour name
  - Price (from €XX)
  - Rating
  - Review count
  - Duration
  - Badges (Best Seller, Likely to Sell Out, etc.)
  - Detail URL

Usage
-----
    python -m scraping.viator.listing_scraper [--url URL] [--headless] [--out file.json]

Example
-------
    python -m scraping.viator.listing_scraper \\
        --url "https://www.viator.com/Barcelona-attractions/Sagrada-Familia/d562-a845" \\
        --out sagrada_tours.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scraping.base.playwright_scraper import PlaywrightScraperBase


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #
_PRICE_RE = re.compile(
    r"(?:(?:€|EUR)\s*([0-9]+(?:[.,][0-9]{1,2})?)"
    r"|([0-9]+(?:[.,][0-9]{1,2})?)\s*(?:€|EUR))",
    re.IGNORECASE,
)


def _parse_price(text: str) -> str | None:
    m = _PRICE_RE.search(text)
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    return raw.replace(",", ".") if raw else None


def _clean(s: str) -> str:
    return " ".join(s.split()).strip()


# ------------------------------------------------------------------ #
# Scraper                                                              #
# ------------------------------------------------------------------ #
class ViatorListingScraper(PlaywrightScraperBase):
    """Scrapes the Viator listing/results page for all tour cards."""

    BASE = "https://www.viator.com"

    # JS that extracts every product card on the current page.
    # Stored as a raw string so Python does not interpret \s, \d etc.
    _CARD_JS = r"""
    () => {
        const cards = [];

        function normalizeText(s) {
            return (s || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
        }

        /** Viator suele mostrar "€ 29", "29 €", "29,99 €", "EUR 29", "From €29"... */
        function extractEurPrice(fullText) {
            const t = normalizeText(fullText);
            let m = t.match(/\u20AC\s*([0-9]+(?:[.,][0-9]{1,2})?)/);
            if (m) return m[1];
            m = t.match(/([0-9]+(?:[.,][0-9]{1,2})?)\s*\u20AC\b/);
            if (m) return m[1];
            m = t.match(/\bEUR\s*([0-9]+(?:[.,][0-9]{1,2})?)\b/i);
            if (m) return m[1];
            m = t.match(/\b(?:from|desde|da)\s*\u20AC\s*([0-9]+(?:[.,][0-9]{1,2})?)\b/i);
            if (m) return m[1];
            return null;
        }

        function looksLikeEurListing(fullText) {
            const t = fullText || '';
            return /\u20AC/.test(t) || /\bEUR\s*[0-9]/i.test(t) || /[0-9]\s*\u20AC/.test(t);
        }

        // Viator wraps each result in an <article> or a classed container
        const candidates = [
            ...document.querySelectorAll('article'),
            ...document.querySelectorAll('[class*="ProductCard"]'),
            ...document.querySelectorAll('[data-testid*="product"]'),
            ...document.querySelectorAll('[class*="productCard"]'),
            ...document.querySelectorAll('[class*="result-card"]'),
            ...document.querySelectorAll('[class*="searchResult"]'),
        ];

        // Deduplicate by element reference
        const seen = new Set();
        const unique = candidates.filter(el => {
            if (seen.has(el)) return false;
            seen.add(el);
            return true;
        });

        for (const el of unique) {
            const fullTextRaw = el.innerText || '';
            if (!looksLikeEurListing(fullTextRaw)) continue;

            // Tour name: first heading or anchor
            let name = '';
            const nameEl = el.querySelector('h2, h3, [class*="title"], [class*="Title"], [class*="name"], [class*="Name"]');
            if (nameEl) name = (nameEl.innerText || '').trim();
            if (!name) {
                const anchor = el.querySelector('a[href*="/tours/"]');
                if (anchor) name = (anchor.innerText || '').trim().split('\n')[0];
            }
            if (!name || name.length < 5) continue;

            const price = extractEurPrice(fullTextRaw);
            if (!price) continue;

            // Rating
            const ratingEl = el.querySelector('[class*="rating"], [class*="Rating"], [aria-label*="rating"], [aria-label*="stars"]');
            let rating = null;
            if (ratingEl) {
                const rm = (ratingEl.innerText || ratingEl.getAttribute('aria-label') || '').match(/([0-9]+(?:\.[0-9]+)?)/);
                if (rm) rating = rm[1];
            }

            // Review count — first (NNN) pattern
            let reviews = null;
            const reviewMatch = fullTextRaw.match(/\(([0-9,]+)\)/);
            if (reviewMatch) reviews = reviewMatch[1].replace(/,/g, '');

            // Duration
            let duration = null;
            const durMatch = fullTextRaw.match(/([0-9]+(?:\.[0-9]+)?\s*(?:hour|hr|minute|min|day)s?(?:\s*[0-9]+\s*(?:minute|min)s?)?)/i);
            if (durMatch) duration = durMatch[1].trim();

            // Badges — skip noise words
            const BADGE_SKIP = new Set(['from', 'price varies by group size', '', 'new']);
            const badgeSet = new Set();
            el.querySelectorAll('[class*="badge"], [class*="Badge"], [class*="label"], [class*="Label"], [class*="tag"]').forEach(b => {
                const t = (b.innerText || '').trim();
                if (t && t.length < 50 && !/\u20AC|\d{2}:\d{2}/.test(t) && !BADGE_SKIP.has(t.toLowerCase()))
                    badgeSet.add(t);
            });

            // Detail URL
            let url = '';
            const linkEl = el.querySelector('a[href*="/tours/"]');
            if (linkEl) url = linkEl.getAttribute('href') || '';

            cards.push({ name, price, rating, reviews, duration, badges: [...badgeSet], url });
        }
        return cards;
    }
    """

    async def _evaluate_cards_with_retry(self, page: Page, *, rounds: int = 5) -> list[dict]:
        """Run _CARD_JS; retry when navigation/SPA replaces the document mid-call."""
        last: Exception | None = None
        for attempt in range(1, rounds + 1):
            try:
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=12000)
                except Exception:
                    pass
                await page.wait_for_timeout(600 + attempt * 200)
                raw = await page.evaluate(self._CARD_JS)
                if isinstance(raw, list):
                    return raw
                return []
            except PlaywrightError as e:
                last = e
                msg = str(e).lower()
                if (
                    "execution context" in msg
                    or "destroyed" in msg
                    or "navigation" in msg
                    or "detached" in msg
                ) and attempt < rounds:
                    await page.wait_for_timeout(800 * attempt)
                    continue
                raise
            except Exception as e:
                last = e
                msg = str(e).lower()
                if (
                    "execution context" in msg
                    or "destroyed" in msg
                    or "navigation" in msg
                ) and attempt < rounds:
                    await page.wait_for_timeout(800 * attempt)
                    continue
                raise
        assert last is not None
        raise last

    async def scrape_listing(
        self,
        listing_url: str,
        *,
        max_scroll_rounds: int = 15,
        stale_rounds_limit: int = 3,
    ) -> list[dict]:
        """Scroll to the bottom repeatedly until no new tours appear.

        Viator uses infinite scroll — there are no "Next page" buttons.
        Each scroll pass loads another batch of results.

        Args:
            listing_url: Viator attraction or results page URL.
            max_scroll_rounds: Hard upper limit on scroll iterations.
            stale_rounds_limit: Stop after this many consecutive rounds
                with zero new tours (end-of-results signal).
        """
        page, ctx = await self.fetch_page(
            listing_url, locale="en-GB", timezone_id="Europe/Madrid"
        )

        all_tours: list[dict] = []
        seen_names: set[str] = set()
        captured_at = datetime.now(UTC).isoformat()
        stale = 0

        try:
            for rnd in range(1, max_scroll_rounds + 1):
                print(f"  [scroll {rnd}] scrolling to bottom...", flush=True)

                # Gradual scroll to the very bottom, triggering lazy-load
                await self._scroll_down(page)

                # Let the network settle after loading new content
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    await page.wait_for_timeout(1500)

                # Extract all visible cards (retry if Viator navigates / hydrates during scroll)
                raw_cards: list[dict] = await self._evaluate_cards_with_retry(page)
                print(f"  [scroll {rnd}] raw cards visible: {len(raw_cards)}", flush=True)

                new_found = 0
                for card in raw_cards:
                    name = _clean(card.get("name", ""))
                    if not name or name in seen_names:
                        continue
                    seen_names.add(name)
                    new_found += 1

                    url = card.get("url", "")
                    if url and not url.startswith("http"):
                        url = urljoin(self.BASE, url)
                    url = url.split("?")[0]  # strip query params

                    all_tours.append(
                        {
                            "name": name,
                            "price_eur": card.get("price"),
                            "rating": card.get("rating"),
                            "reviews": card.get("reviews"),
                            "duration": card.get("duration"),
                            "badges": card.get("badges", []),
                            "url": url,
                            "captured_at": captured_at,
                            "source_listing": listing_url,
                        }
                    )

                print(f"  [scroll {rnd}] +{new_found} new  (total: {len(all_tours)})")

                if new_found == 0:
                    stale += 1
                    if stale >= stale_rounds_limit:
                        # Scroll produced nothing — try clicking a pagination button
                        navigated = await self._try_next_page(page)
                        if navigated:
                            print("  -> Paginated to next page, continuing...")
                            stale = 0  # reset after successful navigation
                            try:
                                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                            except Exception:
                                pass
                            await page.wait_for_timeout(2000)
                        else:
                            print("  -> No new tours and no next page -- end of results.")
                            break
                else:
                    stale = 0  # reset counter on progress

        finally:
            try:
                await ctx.close()
            except Exception:
                pass

        return all_tours

    async def scrape_product_page_snapshot(self, tour_url: str) -> list[dict]:
        """Single tour page (``/tours/.../d562-XXXX``): no result grid — capture title + first € price."""
        page, ctx = await self.fetch_page(
            tour_url, locale="en-GB", timezone_id="Europe/Madrid"
        )
        try:
            await page.wait_for_timeout(1200)
            body = await page.inner_text("body")
            name = await page.evaluate(
                """() => {
                    const h = document.querySelector('h1');
                    return (h && h.innerText ? h.innerText.trim() : '') || document.title || '';
                }"""
            )
            name = _clean(name)[:500]
            price_token = _parse_price(body)
            if not name or len(name) < 5 or not price_token:
                return []
            captured_at = datetime.now(UTC).isoformat()
            clean_url = tour_url.split("?")[0]
            return [
                {
                    "name": name,
                    "price_eur": price_token,
                    "rating": None,
                    "reviews": None,
                    "duration": None,
                    "badges": [],
                    "url": clean_url,
                    "captured_at": captured_at,
                    "source_listing": tour_url,
                }
            ]
        finally:
            try:
                await ctx.close()
            except Exception:
                pass

    async def _scroll_down(self, page: Page) -> None:
        """Scroll smoothly from current position to the very bottom.

        Uses small increments so Viator's intersection-observer triggers
        load-more for each batch of cards as they enter the viewport.
        """
        try:
            viewport_h: int = await page.evaluate("window.innerHeight")
            step = max(viewport_h, 400)
            pos: int = await page.evaluate("window.scrollY")
            total_h: int = await page.evaluate("document.body.scrollHeight")

            while pos < total_h:
                pos = min(pos + step, total_h)
                await page.evaluate(f"window.scrollTo(0, {pos})")
                await page.wait_for_timeout(350)
                # Recalculate height after potential new content
                total_h = await page.evaluate("document.body.scrollHeight")

            # Pause briefly at bottom before we extract cards
            await page.wait_for_timeout(800)
        except Exception:
            pass

    async def _try_next_page(self, page: Page) -> bool:
        """Try to click a 'Next page' button. Returns True if navigation succeeded.

        Viator attraction pages often use numbered pagination; search result
        pages sometimes use infinite scroll instead.  We try both patterns.
        """
        next_sels = [
            # Numbered pagination arrows
            "a[aria-label='Next page']",
            "button[aria-label='Next page']",
            "[data-testid='pagination-next']",
            "a[rel='next']",
            # Load-more / show-more buttons
            "button:has-text('Load more')",
            "button:has-text('Show more')",
            "button:has-text('Ver más')",
            # Generic next button in pagination controls
            ".pagination [aria-label*='next' i]",
            "[class*='pagination'] [aria-label*='next' i]",
            # Numbered pagination: find the current active page and click the next sibling
            "[class*='pagination'] [aria-current='page'] ~ *",
        ]
        for sel in next_sels:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.scroll_into_view_if_needed(timeout=2000)
                    await btn.click(timeout=3000)
                    # Wait for the new page content to settle
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass
                    try:
                        await page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        await page.wait_for_timeout(3000)
                    # Scroll back to top for the next extraction pass
                    await page.evaluate("window.scrollTo(0, 0)")
                    await page.wait_for_timeout(1200)
                    return True
            except Exception:
                continue
        return False


# ------------------------------------------------------------------ #
# CLI                                                                  #
# ------------------------------------------------------------------ #
async def run(url: str, out: str | None, headless: bool, max_scrolls: int) -> None:
    scraper = ViatorListingScraper(headless=headless)
    print(f"\nScraping listing: {url}")
    print(f"Max scroll rounds: {max_scrolls} | Headless: {headless}")
    print("-" * 60)

    try:
        tours = await scraper.scrape_listing(url, max_scroll_rounds=max_scrolls)
    finally:
        await scraper.close()

    print(f"\n{'='*60}")
    print(f"TOTAL TOURS FOUND: {len(tours)}")
    print(f"{'='*60}")
    for i, t in enumerate(tours, 1):
        badges = f"  [{', '.join(t['badges'])}]" if t["badges"] else ""
        price = f"{t['price_eur']} EUR" if t["price_eur"] else "no price"
        rating = f"{t['rating']} stars ({t['reviews']} reviews)" if t["rating"] else ""
        dur = f" | {t['duration']}" if t["duration"] else ""
        print(f"  {i:3d}. {t['name']}")
        print(f"       {price}{dur} | {rating}{badges}")

    # Save to JSON
    output_path = out or "viator_tours.json"
    Path(output_path).write_text(
        json.dumps(tours, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nSaved {len(tours)} tours -> {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape all tours from a Viator listing page.")
    parser.add_argument(
        "--url",
        default="https://www.viator.com/Barcelona-attractions/Sagrada-Familia/d562-a845",
        help="Viator attraction/results page URL",
    )
    parser.add_argument(
        "--out",
        default="data/viator_tours.json",
        help="Output JSON file (default: data/viator_tours.json)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Show browser window",
    )
    parser.add_argument(
        "--scrolls",
        type=int,
        default=15,
        help="Max scroll rounds before stopping (default: 15)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.url, args.out, not args.no_headless, args.scrolls))


if __name__ == "__main__":
    main()
