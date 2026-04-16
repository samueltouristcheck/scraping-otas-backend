import asyncio
from scraping.getyourguide.scraper import GetYourGuideScraper

URL = "https://www.getyourguide.es/barcelona-l45/sagrada-familia-ticket-de-entrada-sin-colas-t50027/?date_from=2026-03-07&date_to=2026-03-07"


async def main() -> None:
    scraper = GetYourGuideScraper(headless=True, max_retries=1, timeout_ms=60000)
    page, context = await scraper.fetch_page(URL, locale="es-ES", timezone_id="Europe/Madrid")
    body = await page.inner_text("body")
    print("blocked", "ray id" in body.lower() or "se ha producido un error" in body.lower())

    payload = await page.evaluate(
        """
() => {
  const all = [...document.querySelectorAll('*')];
  const pick = (needle) => all
    .filter((e) => (e.textContent || '').toLowerCase().includes(needle))
    .slice(0, 12)
    .map((e) => ({
      tag: e.tagName,
      id: e.id || null,
      cls: e.className || null,
      role: e.getAttribute('role'),
      text: (e.textContent || '').trim().slice(0, 140)
    }));

  return {
    buttons: document.querySelectorAll('button').length,
    links: document.querySelectorAll('a').length,
    checkAvailabilityNodes: pick('comprueba la disponibilidad'),
    startTimeNodes: pick('hora de inicio'),
    exposedOptionsContainers: document.querySelectorAll('#exposedOptionsContentIdentifierV2').length,
    optionCards: document.querySelectorAll('[data-test-id="sdui-ba-available-option-card"]').length
  };
}
        """
    )
    print(payload)

    await scraper._open_booking_options(page)
    payload_after_open = await page.evaluate(
        """
() => {
  const pickText = (selector) => [...document.querySelectorAll(selector)]
    .slice(0, 8)
    .map((e) => (e.textContent || '').trim());
  return {
    optionCardsById: document.querySelectorAll('[id^="option-card-"]').length,
    optionContainers: document.querySelectorAll('.activity-option-container').length,
    optionWrappers: document.querySelectorAll('details.activity-option-wrapper').length,
    startingContainers: document.querySelectorAll('.starting-times__container').length,
    startingTexts: pickText('.starting-times__container'),
    optionTitles: pickText('.activity-option-container .title, [id^="option-card-"] .title')
  };
}
        """
    )
    print(payload_after_open)

    state_probe = await page.evaluate(
        """
() => {
  const root = window.__INITIAL_STATE__ || {};
  const matches = [];
  const queue = [{ path: 'root', value: root }];
  const seen = new Set();

  while (queue.length && matches.length < 120) {
    const { path, value } = queue.shift();
    if (!value || typeof value !== 'object') continue;
    if (seen.has(value)) continue;
    seen.add(value);

    if (Array.isArray(value)) {
      value.slice(0, 20).forEach((item, idx) => queue.push({ path: `${path}[${idx}]`, value: item }));
      continue;
    }

    for (const [key, child] of Object.entries(value)) {
      const childPath = `${path}.${key}`;
      const keyLower = key.toLowerCase();
      if (['slot', 'start', 'time', 'availability', 'option', 'calendar', 'booking'].some((k) => keyLower.includes(k))) {
        matches.push(childPath);
      }
      if (typeof child === 'object' && child !== null) {
        queue.push({ path: childPath, value: child });
      }
      if (matches.length >= 120) break;
    }
  }

  return {
    hasInitialState: !!window.__INITIAL_STATE__,
    topKeys: Object.keys(root).slice(0, 40),
    matchPaths: matches
  };
}
        """
    )
    print(state_probe)

    state_string_matches = await page.evaluate(
        """
() => {
  const root = window.__INITIAL_STATE__ || {};
  const out = [];
  const queue = [{ path: 'root', value: root }];
  const seen = new Set();

  while (queue.length && out.length < 200) {
    const item = queue.shift();
    const path = item.path;
    const value = item.value;
    if (!value || typeof value !== 'object') continue;
    if (seen.has(value)) continue;
    seen.add(value);

    if (Array.isArray(value)) {
      value.slice(0, 30).forEach((child, idx) => {
        queue.push({ path: path + '[' + idx + ']', value: child });
      });
      continue;
    }

    for (const [key, child] of Object.entries(value)) {
      const childPath = path + '.' + key;
      if (typeof child === 'string') {
        const low = child.toLowerCase();
        if (
          low.includes('/api') ||
          low.includes('availability') ||
          low.includes('booking') ||
          low.includes('option') ||
          low.includes('timeslot') ||
          low.includes('starttime')
        ) {
          out.push({ path: childPath, value: child.slice(0, 300) });
          if (out.length >= 200) break;
        }
      } else if (typeof child === 'object' && child !== null) {
        queue.push({ path: childPath, value: child });
      }
    }
  }

  return out;
}
        """
    )
    print({"stringMatchesCount": len(state_string_matches)})
    for row in state_string_matches[:80]:
        print(row)

    sdui_cards = await page.evaluate(
        """
() => {
  const root = window.__INITIAL_STATE__ || {};
  const layoutContent = (((root.sdui || {}).layout || {}).content || []);
  const section = layoutContent[5] || {};
  const sectionContent = section.content || [];
  const firstColumn = sectionContent[0] || {};
  const firstColumnContent = firstColumn.content || [];
  const exposedRoot = firstColumnContent[10] || {};
  const exposedContent = exposedRoot.content || [];
  const adaptiveContainer = exposedContent[2] || {};
  const cards = adaptiveContainer.content || [];

  return cards.slice(0, 8).map((card) => ({
    id: card.id,
    type: card.type,
    keys: Object.keys(card || {}),
    contentKeys: card.content ? Object.keys(card.content) : [],
    contentPreview: card.content || null
  }));
}
        """
    )
    print({"sduiCardsCount": len(sdui_cards)})
    for card in sdui_cards:
        print(card)

    recursive_cards = await page.evaluate(
        """
() => {
  const root = window.__INITIAL_STATE__ || {};
  const found = [];
  const queue = [root];
  const seen = new Set();

  while (queue.length && found.length < 12) {
    const current = queue.shift();
    if (!current || typeof current !== 'object') continue;
    if (seen.has(current)) continue;
    seen.add(current);

    if (!Array.isArray(current)) {
      const id = current.id;
      if (typeof id === 'string' && id.startsWith('option-card-')) {
        found.push({
          id,
          keys: Object.keys(current),
          type: current.type || null,
          contentKeys: current.content ? Object.keys(current.content) : [],
          contentPreview: current.content || null,
          detailsKeys: current.details ? Object.keys(current.details) : [],
          payloadKeys: current.payload ? Object.keys(current.payload) : []
        });
      }
      Object.values(current).forEach((child) => {
        if (child && typeof child === 'object') queue.push(child);
      });
    } else {
      current.slice(0, 50).forEach((child) => {
        if (child && typeof child === 'object') queue.push(child);
      });
    }
  }

  return found;
}
        """
    )
    print({"recursiveCardsCount": len(recursive_cards)})
    for card in recursive_cards:
        print(card)

    await context.close()
    await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
