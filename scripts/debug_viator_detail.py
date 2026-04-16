"""Debug script: open a Viator tour detail page and dump all buttons + interactive elements."""
import asyncio
import sys
sys.path.insert(0, r"c:\Users\PC\Desktop\scraping-otas")

from scraping.base.playwright_scraper import PlaywrightScraperBase


async def main(url: str) -> None:
    base = PlaywrightScraperBase(headless=False, timeout_ms=30_000)
    page, ctx = await base.fetch_page(url, locale="en-GB", timezone_id="Europe/Madrid")

    try:
        print(f"\n=== PAGE TITLE ===\n{await page.title()}\n")

        # ── All buttons ───────────────────────────────────────────────
        btns = await page.eval_on_selector_all(
            "button",
            """els => els.map(el => ({
                text: (el.innerText || '').trim().slice(0, 80),
                testid: el.getAttribute('data-testid') || '',
                cls: el.className?.slice(0, 80) || '',
                visible: el.offsetParent !== null,
            }))"""
        )
        print(f"=== BUTTONS ({len(btns)}) ===")
        for b in btns:
            vis = "✓" if b["visible"] else " "
            print(f"  [{vis}] text={b['text']!r:50s}  testid={b['testid']!r:40s}  cls_prefix={b['cls'][:40]!r}")

        # ── data-testid elements ──────────────────────────────────────
        testids = await page.eval_on_selector_all(
            "[data-testid]",
            """els => els.map(el => ({
                testid: el.getAttribute('data-testid'),
                tag: el.tagName,
                text: (el.innerText || '').trim().slice(0, 60),
            }))"""
        )
        print(f"\n=== DATA-TESTID ELEMENTS ({len(testids)}) ===")
        seen = set()
        for t in testids:
            tid = t["testid"]
            if tid not in seen:
                seen.add(tid)
                print(f"  [{t['tag']:10s}] {tid!r:55s}  text={repr(t['text'])[:40]}")

        # ── All visible link hrefs (to confirm detail URL pattern) ────
        hrefs = await page.eval_on_selector_all(
            "a[href*='/tours/']",
            "els => [...new Set(els.map(e => e.getAttribute('href')))].slice(0, 20)"
        )
        print(f"\n=== TOUR LINKS (sample) ===")
        for h in hrefs:
            print(f"  {h}")

        print("\n[Pausing 60 s — inspect the browser window, then this script exits]")
        await asyncio.sleep(60)

    finally:
        await ctx.close()
        await base.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else (
        "https://www.viator.com/tours/Barcelona/"
        "Sagrada-Familia-Guided-express-english-tour/d562-190179P1"
    )
    asyncio.run(main(target))
