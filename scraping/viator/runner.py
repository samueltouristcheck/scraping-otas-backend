"""Standalone runner for the Viator scraper.

Usage
-----
    python -m scraping.viator.runner <listing_url> [--days 7] [--headless]

Example
-------
    python -m scraping.viator.runner \
        "https://www.viator.com/Barcelona-attractions/Sagrada-Familia/d562-a845" \
        --days 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime

from scraping.viator.scraper import ViatorScraper


async def run(source_url: str, days: int = 1, headless: bool = True) -> None:
    scraper = ViatorScraper(headless=headless)
    horizons = scraper.default_horizons(
        reference_date=datetime.now(UTC).date(),
        daily_window_days=days,
    )

    print(f"Scraping Viator | {source_url}")
    print(f"Horizons: {len(horizons)} days  (today + {days} days)")
    print("-" * 60)

    result = await scraper.scrape(source_url=source_url, horizons=horizons)

    # Pretty-print summary
    print(f"\nProduct  : {result.product_name}")
    print(f"OTA      : {result.ota_name}")
    print(f"Captured : {result.captured_at}")
    print(f"Options  : {result.options}")
    print(f"Slots    : {sorted(str(s) for s in (result.slots or []))}")
    print(f"Prices   : {len(result.prices)} rows")
    print(f"Avail    : {len(result.availability)} rows")

    if result.prices:
        print("\n--- Price rows (first 20) ---")
        for p in result.prices[:20]:
            print(
                f"  {p.target_date} | h={p.horizon_days:3d}d "
                f"| slot={p.slot_time} "
                f"| {p.option_name!r} "
                f"| {p.language_code} "
                f"| €{p.final_price}"
            )

    if result.availability:
        print("\n--- Availability rows (first 20) ---")
        for a in result.availability[:20]:
            seats = f"  seats={a.seats_available}" if a.seats_available else ""
            print(
                f"  {a.target_date} | h={a.horizon_days:3d}d "
                f"| slot={a.slot_time} "
                f"| {a.option_name!r} "
                f"| available={a.is_available}{seats}"
            )

    print("\n--- Full JSON ---")
    print(result.model_dump_json(indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Viator scraper for a listing URL."
    )
    parser.add_argument(
        "source_url",
        nargs="?",
        default="https://www.viator.com/Barcelona-attractions/Sagrada-Familia/d562-a845",
        help="Viator attraction or listing URL",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Number of horizon days to scrape (default: 1 = today only)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Show the browser window (useful for debugging)",
    )
    args = parser.parse_args()

    asyncio.run(
        run(
            source_url=args.source_url,
            days=args.days,
            headless=not args.no_headless,
        )
    )


if __name__ == "__main__":
    main()
