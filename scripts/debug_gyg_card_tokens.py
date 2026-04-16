import asyncio
import re

from playwright.async_api import async_playwright

URL = "https://www.getyourguide.es/sagrada-familia-l2699/?date_from=2026-03-02&date_to=2026-03-02"
TOKENS = ["vendido", "reserv", "ayer", "top pick", "best seller", "mejor valorados"]
CARD_SELECTORS = [
    "article[class*='activity-card']",
    "[data-test-id*='activity-card']",
    "article:has([data-testid*='price'])",
    "li:has([data-testid*='price'])",
]


async def main() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(locale="es-ES", timezone_id="Europe/Madrid")
        page = await context.new_page()
        await page.goto(URL, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(5000)

        body = await page.inner_text("body")
        lowered_body = body.lower()
        blocked = any(token in lowered_body for token in ["ray id", "se ha producido un error", "access denied", "attention required"])
        print("blocked_page=", blocked)

        cards = []
        for selector in CARD_SELECTORS:
            blocks = await page.eval_on_selector_all(
                selector,
                "elements => elements.map(e => (e.innerText || '').trim()).filter(Boolean)",
            )
            blocks = [block for block in blocks if "€" in block or "EUR" in block]
            if blocks:
                print(f"selector={selector} hits={len(blocks)}")
                cards.extend(blocks)

        if not cards:
            cards = await page.eval_on_selector_all(
                "article, li, div",
                "elements => elements.map(e => (e.innerText || '').trim()).filter(t => t && (t.includes('EUR') || t.includes('€')))"
            )

        print("cards_with_price=", len(cards))
        for token in TOKENS:
            hits = [c for c in cards if token.lower() in c.lower()]
            print(f"token={token} hits={len(hits)}")
            if hits:
                print("sample_start")
                print(hits[0][:1200])
                print("sample_end")

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
