import asyncio, sys
sys.path.insert(0, "/app")

async def main():
    from scraping.getyourguide.scraper import GetYourGuideScraper
    from datetime import date

    s = GetYourGuideScraper()
    target_date = date(2026, 3, 12)

    # Use the detail URL from listing that we know works
    detail_url = "https://www.getyourguide.es/sagrada-familia-l2699/barcelona-visita-guiada-sin-hacer-cola-a-la-sagrada-familia-t137471/"
    dated_url = s._url_for_date(detail_url, target_date)
    print(f"Testing: {dated_url}", flush=True)

    options = await s._scrape_detail_page(dated_url, target_date=target_date)
    print(f"\n=== RESULT ===", flush=True)
    print(f"Options found: {len(options)}", flush=True)
    for opt in options:
        print(f"  name={opt.get('option_name','?')[:50]}", flush=True)
        print(f"  slot_times={opt.get('slot_times','?')}", flush=True)
        print(f"  price={opt.get('price','?')}", flush=True)
        print(f"  available={opt.get('is_available','?')}", flush=True)
        print(flush=True)

    await s.close()

asyncio.run(main())
