import asyncio
from datetime import UTC, datetime

from scraping.getyourguide.scraper import GetYourGuideScraper


async def run(source_url: str) -> None:
    scraper = GetYourGuideScraper(headless=True)
    horizons = scraper.default_horizons(reference_date=datetime.now(UTC).date())
    result = await scraper.scrape(source_url=source_url, horizons=horizons)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run GetYourGuide scraper for a product URL")
    parser.add_argument("source_url", help="GetYourGuide product URL")
    args = parser.parse_args()

    asyncio.run(run(args.source_url))
