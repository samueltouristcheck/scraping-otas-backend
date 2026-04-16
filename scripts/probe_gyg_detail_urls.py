import asyncio
import re

from scraping.getyourguide.scraper import GetYourGuideScraper

LIST_URL = "https://www.getyourguide.es/sagrada-familia-l2699/?date_from=2026-03-07&date_to=2026-03-07"


async def main() -> None:
    scraper = GetYourGuideScraper(headless=True, max_retries=1, timeout_ms=60000)
    page, context = await scraper.fetch_page(LIST_URL, locale="es-ES", timezone_id="Europe/Madrid")
    detail_urls = await scraper._extract_detail_urls(page, base_url=LIST_URL, expected_phrase="sagrada familia")
    await context.close()

    print("urls", len(detail_urls))
    for detail_url in detail_urls[:10]:
        detail_page = None
        detail_context = None
        try:
            detail_page, detail_context = await scraper.fetch_page(detail_url, locale="es-ES", timezone_id="Europe/Madrid")
            await scraper._open_booking_options(detail_page)
            stats = await detail_page.evaluate(
                """
() => ({
  optionCardsById: document.querySelectorAll('[id^="option-card-"]').length,
  optionWrappers: document.querySelectorAll('details.activity-option-wrapper').length,
  startingContainers: document.querySelectorAll('.starting-times__container').length,
    hasStartLabel: (document.body.innerText || '').toLowerCase().includes('hora de inicio'),
    cardSnippets: Array.from(document.querySelectorAll('[id^="option-card-"]')).slice(0, 3).map((el) => (el.innerText || '').slice(0, 800)),
    cardTimes: Array.from(document.querySelectorAll('[id^="option-card-"]')).slice(0, 3).map((el) => {
        const text = (el.innerText || '');
        const matches = text.match(/\b([01]?\d|2[0-3]):([0-5]\d)\b/g) || [];
        return matches;
    }),
    cardSeatMentions: Array.from(document.querySelectorAll('[id^="option-card-"]')).slice(0, 3).map((el) => {
        const text = (el.innerText || '').toLowerCase();
        return text.includes('plaza disponible') || text.includes('plazas disponibles');
    })
})
                """
            )
            select_count = await detail_page.locator("button:has-text('Seleccionar')").count()
            post_click = {"selectButtons": select_count, "hasStartLabelAfterClick": False, "timesAfterClick": []}
            if select_count > 0:
                try:
                    await detail_page.locator("button:has-text('Seleccionar')").first.click(timeout=4000)
                    await detail_page.wait_for_timeout(2200)
                    post_text = await detail_page.inner_text("body")
                    time_matches = re.findall(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", post_text)
                    post_click = {
                        "selectButtons": select_count,
                        "hasStartLabelAfterClick": "hora de inicio" in post_text.lower(),
                        "timesAfterClick": [f"{h}:{m}" for h, m in time_matches[:20]],
                    }
                except Exception:
                    pass

            print(detail_url)
            print(stats)
            print(post_click)
        except Exception as exc:
            print("ERR", detail_url, str(exc)[:180])
        finally:
            if detail_context is not None:
                await detail_context.close()

    await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
