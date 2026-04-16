import asyncio
import re

from playwright.async_api import async_playwright

URL = "https://www.getyourguide.es/sagrada-familia-l2699/?date_from=2026-03-02&date_to=2026-03-02"
BADGE_REGEX = re.compile(r"se\s+reserv[oó]\s+\d+\s+veces\s+ayer", flags=re.IGNORECASE)


async def main() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(locale="es-ES", timezone_id="Europe/Madrid")
        page = await context.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(3000)

        body = await page.inner_text("body")
        body_hits = BADGE_REGEX.findall(body)
        print("HAS_BADGE_IN_BODY=", bool(body_hits))
        print("BODY_HITS=", body_hits[:10])

        card_texts = await page.eval_on_selector_all(
            "article, li, div",
            "elements => elements.map(e => (e.innerText || '').trim()).filter(Boolean)",
        )
        card_hits = [text for text in card_texts if BADGE_REGEX.search(text)]
        print("CARD_HITS_COUNT=", len(card_hits))
        if card_hits:
            print("SAMPLE_CARD_START")
            print(card_hits[0][:1500])
            print("SAMPLE_CARD_END")

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
