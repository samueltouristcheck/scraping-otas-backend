# Frontend Integration Handoff

Use this document to connect the frontend to the OTA Competitive Intelligence backend.

## Backend runtime

- Local API base URL: `http://localhost:8001`
- API prefix: `/api/v1`
- Full base URL for frontend: `http://localhost:8001/api/v1`
- OpenAPI docs: `http://localhost:8001/docs`

## CORS

Backend allows origins from env var `FRONTEND_ORIGINS`.
Current value in `.env`:

- `http://localhost:3000`
- `http://localhost:5173`

If your frontend uses another host/port, add it to `FRONTEND_ORIGINS`.

## Implemented endpoints

### 1) List monitored tours

`GET /api/v1/tours`

Response: `TourResponse[]`

```json
[
  {
    "id": "uuid",
    "internal_code": "SAGRADA_REGULAR_LARGE",
    "attraction": "Sagrada Familia",
    "variant": "Regular / Large groups",
    "city": "Barcelona",
    "market": "ES",
    "is_active": true
  }
]
```

### 2) List sources by tour

`GET /api/v1/sources?tour_code=SAGRADA_REGULAR_LARGE`

Response: `SourceResponse[]`

```json
[
  {
    "id": "uuid",
    "tour_id": "uuid",
    "ota_name": "getyourguide",
    "external_product_id": "sagrada-familia-l2699",
    "product_url": "https://www.getyourguide.es/sagrada-familia-l2699/",
    "default_currency": "EUR",
    "default_locale": "en",
    "is_active": true
  }
]
```

### 3) Latest price snapshot

`GET /api/v1/prices/latest?tour_code=SAGRADA_REGULAR_LARGE&horizon_days=7&limit=500`

or for a whole rolling window:

`GET /api/v1/prices/latest?tour_code=SAGRADA_REGULAR_LARGE&range_days=7&limit=500`

Optional OTA filter:

`GET /api/v1/prices/latest?tour_code=SAGRADA_REGULAR_LARGE&ota_name=getyourguide&range_days=7`

- `horizon_days` optional
- `range_days` optional (returns target dates from today to today+N; if present, it overrides `horizon_days`)
- `limit` optional (default 500)

Response: `LatestPricesResponse`

```json
{
  "tour_code": "SAGRADA_REGULAR_LARGE",
  "observed_at": "2026-03-02T11:10:46.634374Z",
  "items": [
    {
      "id": 5,
      "ota_source_id": "uuid",
      "ota_name": "getyourguide",
      "target_date": "2026-03-09",
      "horizon_days": 7,
      "slot_time": null,
      "language_code": null,
      "option_name": "guided tour",
      "currency_code": "EUR",
      "list_price": "34.00",
      "final_price": "34.00",
      "observed_at": "2026-03-02T11:10:46.634374Z"
    }
  ]
}
```

### 4) Latest availability snapshot

`GET /api/v1/availability/latest?tour_code=SAGRADA_REGULAR_LARGE&horizon_days=7&limit=500`

or for a whole rolling window:

`GET /api/v1/availability/latest?tour_code=SAGRADA_REGULAR_LARGE&range_days=7&limit=500`

Optional OTA filter:

`GET /api/v1/availability/latest?tour_code=SAGRADA_REGULAR_LARGE&ota_name=getyourguide&range_days=7`

- `horizon_days` optional
- `range_days` optional (returns target dates from today to today+N; if present, it overrides `horizon_days`)
- `limit` optional (default 500)

Response: `LatestAvailabilityResponse`

```json
{
  "tour_code": "SAGRADA_REGULAR_LARGE",
  "observed_at": "2026-03-02T11:10:46.634374Z",
  "items": [
    {
      "id": 5,
      "ota_source_id": "uuid",
      "ota_name": "getyourguide",
      "target_date": "2026-03-09",
      "horizon_days": 7,
      "slot_time": null,
      "language_code": null,
      "option_name": "guided tour",
      "is_available": true,
      "seats_available": null,
      "observed_at": "2026-03-02T11:10:46.634374Z"
    }
  ]
}
```

### 5) Price timeseries

`GET /api/v1/prices/timeseries?tour_code=SAGRADA_REGULAR_LARGE&horizon_days=7&from_date=2026-03-01&to_date=2026-03-31&limit=5000`

- `horizon_days` optional
- `from_date` optional (YYYY-MM-DD)
- `to_date` optional (YYYY-MM-DD)
- `limit` optional (default 5000, max 20000)

Response: `PriceTimeseriesResponse`

```json
{
  "tour_code": "SAGRADA_REGULAR_LARGE",
  "items": [
    {
      "id": 5,
      "ota_source_id": "uuid",
      "ota_name": "getyourguide",
      "target_date": "2026-03-09",
      "horizon_days": 7,
      "slot_time": null,
      "language_code": null,
      "option_name": "guided tour",
      "currency_code": "EUR",
      "list_price": "34.00",
      "final_price": "34.00",
      "observed_at": "2026-03-02T11:10:46.634374Z"
    }
  ]
}
```

### 6) Availability heatmap (monthly overview)

`GET /api/v1/availability/heatmap?tour_code=SAGRADA_REGULAR_LARGE&range_days=30`

or explicit range:

`GET /api/v1/availability/heatmap?tour_code=SAGRADA_REGULAR_LARGE&from_date=2026-03-01&to_date=2026-03-31`

- `ota_name` optional
- `range_days` optional
- `from_date` optional
- `to_date` optional

Response: `AvailabilityHeatmapResponse`

```json
{
  "tour_code": "SAGRADA_REGULAR_LARGE",
  "ota_name": "getyourguide",
  "from_date": "2026-03-01",
  "to_date": "2026-03-31",
  "observed_at": "2026-03-04T12:21:57.623000Z",
  "kpis": {
    "availability_rate_7d": 0.92,
    "availability_rate_30d": 0.88,
    "sold_out_days": 1,
    "critical_slots": 8,
    "wow_current_week_rate": 0.90,
    "wow_previous_week_rate": 0.85,
    "wow_delta": 0.05
  },
  "days": [
    {
      "target_date": "2026-03-04",
      "level": "high",
      "availability_rate": 0.95,
      "available_slots": 19,
      "total_slots": 20,
      "avg_final_price": "56.40",
      "currency_code": "EUR"
    }
  ]
}
```

### 7) Availability day detail (drill-down)

`GET /api/v1/availability/day-detail?tour_code=SAGRADA_REGULAR_LARGE&target_date=2026-03-04`

Optional OTA filter:

`GET /api/v1/availability/day-detail?tour_code=SAGRADA_REGULAR_LARGE&target_date=2026-03-04&ota_name=getyourguide`

Response: `AvailabilityDayDetailResponse`

```json
{
  "tour_code": "SAGRADA_REGULAR_LARGE",
  "ota_name": "getyourguide",
  "target_date": "2026-03-04",
  "observed_at": "2026-03-04T12:21:57.623000Z",
  "slots": [
    {
      "target_date": "2026-03-04",
      "slot_time": "09:00:00",
      "is_available": true,
      "seats_available": null,
      "ota_name": "getyourguide",
      "option_name": "ticket de acceso a la sagrada familia con audioguía",
      "language_code": null,
      "final_price": "34.00",
      "list_price": "34.00",
      "currency_code": "EUR",
      "popularity_count_yesterday": 47,
      "popularity_label": "popular",
      "observed_at": "2026-03-04T12:21:57.623000Z"
    }
  ]
}
```

## TypeScript contracts (copy-paste)

```ts
export type UUID = string;

export interface TourResponse {
  id: UUID;
  internal_code: string;
  attraction: string;
  variant: string;
  city: string;
  market: string;
  is_active: boolean;
}

export interface SourceResponse {
  id: UUID;
  tour_id: UUID;
  ota_name: string;
  external_product_id: string;
  product_url: string;
  default_currency: string;
  default_locale: string;
  is_active: boolean;
}

export interface PricePointResponse {
  id: number;
  ota_source_id: UUID;
  ota_name: string | null;
  target_date: string; // YYYY-MM-DD
  horizon_days: number;
  slot_time: string | null; // HH:MM:SS
  language_code: string | null;
  option_name: string | null;
  currency_code: string;
  list_price: string; // Decimal serialized as string
  final_price: string | null; // Decimal serialized as string
  popularity_count_yesterday: number | null;
  popularity_label: string | null;
  observed_at: string; // ISO datetime
}

export interface AvailabilityPointResponse {
  id: number;
  ota_source_id: UUID;
  ota_name: string | null;
  target_date: string;
  horizon_days: number;
  slot_time: string | null;
  language_code: string | null;
  option_name: string | null;
  is_available: boolean;
  seats_available: number | null;
  observed_at: string;
}

export interface LatestPricesResponse {
  tour_code: string;
  observed_at: string | null;
  items: PricePointResponse[];
}

export interface LatestAvailabilityResponse {
  tour_code: string;
  observed_at: string | null;
  items: AvailabilityPointResponse[];
}

export interface PriceTimeseriesResponse {
  tour_code: string;
  items: PricePointResponse[];
}

export interface HeatmapDayResponse {
  target_date: string;
  level: "high" | "medium" | "low" | "no-data";
  availability_rate: number;
  available_slots: number;
  total_slots: number;
  avg_final_price: string | null;
  currency_code: string | null;
}

export interface AvailabilityKpiResponse {
  availability_rate_7d: number;
  availability_rate_30d: number;
  sold_out_days: number;
  critical_slots: number;
  wow_current_week_rate: number;
  wow_previous_week_rate: number;
  wow_delta: number;
}

export interface AvailabilityHeatmapResponse {
  tour_code: string;
  ota_name: string | null;
  from_date: string;
  to_date: string;
  observed_at: string | null;
  kpis: AvailabilityKpiResponse;
  days: HeatmapDayResponse[];
}

export interface AvailabilityDaySlotResponse {
  target_date: string;
  slot_time: string | null;
  is_available: boolean;
  seats_available: number | null;
  ota_name: string | null;
  option_name: string | null;
  language_code: string | null;
  final_price: string | null;
  list_price: string | null;
  currency_code: string | null;
  popularity_count_yesterday: number | null;
  popularity_label: string | null;
  observed_at: string;
}

export interface AvailabilityDayDetailResponse {
  tour_code: string;
  ota_name: string | null;
  target_date: string;
  observed_at: string | null;
  slots: AvailabilityDaySlotResponse[];
}
```

## Frontend fetch examples

```ts
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL; // e.g. http://localhost:8001/api/v1

export async function getTours(): Promise<TourResponse[]> {
  const res = await fetch(`${API_BASE_URL}/tours`);
  if (!res.ok) throw new Error(`GET /tours failed: ${res.status}`);
  return res.json();
}

export async function getLatestPrices(tourCode: string, horizonDays?: number): Promise<LatestPricesResponse> {
  const params = new URLSearchParams({ tour_code: tourCode });
  if (horizonDays !== undefined) params.set("horizon_days", String(horizonDays));

  const res = await fetch(`${API_BASE_URL}/prices/latest?${params.toString()}`);
  if (!res.ok) throw new Error(`GET /prices/latest failed: ${res.status}`);
  return res.json();
}
```

## UI mapping suggestion

- Tour selector from `/tours`
- OTA/source badge from `/sources?tour_code=...`
- Current snapshot cards from:
  - `/prices/latest`
  - `/availability/latest`
- Trend chart from `/prices/timeseries`
- Horizon tabs: `[0, 7, 30, 90, 180]`

## Important implementation notes

1. Decimal fields are serialized as strings (`"34.00"`), parse to number in frontend if needed.
2. `observed_at` is UTC ISO datetime.
3. `slot_time` / `language_code` / `option_name` can be `null`.
4. Empty result is valid (`items: []`) when no snapshot exists.

## Current data state

- Tours seeded: 3
- Sources seeded: 1 (`getyourguide` / `sagrada-familia-l2699`)
- Prices stored: yes
- Availability stored: yes

---

## Viator listing scraper

The Viator listing scraper (`scraping/viator/listing_scraper.py`) works independently of the database.  
It scrolls through a Viator attraction page and dumps all tour cards to a **flat JSON file**.  
It is not yet wired to the API — the frontend must load the file directly or you can serve it as a static asset / add a thin endpoint.

### How to run it

```bash
python -m scraping.viator.listing_scraper \
  --url "https://www.viator.com/Barcelona-attractions/Sagrada-Familia/d562-a845" \
  --scrolls 20 \
  --out viator_sagrada_tours.json \
  --no-headless
```

| Flag | Default | Description |
|---|---|---|
| `--url` | Sagrada Família page | Any Viator attraction or search-results URL |
| `--scrolls` | `15` | Max scroll rounds (each round = one full page scroll + optional pagination click) |
| `--out` | `viator_tours.json` | Output file path |
| `--no-headless` | off | Show browser window — **required** to bypass Cloudflare bot detection |

> **Bot detection note:** Running in headless mode returns 0 results because Viator's Cloudflare blocks headless Chromium.  
> Always use `--no-headless` when running this scraper.

### Output JSON schema

```json
[
  {
    "name": "Sagrada Familia Guided Tour with Skip the Line Ticket",
    "price_eur": "47",
    "rating": "4.7",
    "reviews": "3091",
    "duration": "1 hour 15 minutes",
    "badges": ["Best Seller"],
    "url": "https://www.viator.com/tours/Barcelona/Sagrada-Familia-Guided-Tour/d562-190179P1",
    "captured_at": "2026-03-11T10:22:00.000000+00:00",
    "source_listing": "https://www.viator.com/Barcelona-attractions/Sagrada-Familia/d562-a845"
  }
]
```

All numeric fields (`price_eur`, `rating`, `reviews`) are serialized as **strings** — parse them on the frontend.

### TypeScript types

```ts
export interface ViatorTourCard {
  name: string;
  price_eur: string | null;       // "47" — parse to number when needed
  rating: string | null;          // "4.7"
  reviews: string | null;         // "3091"
  duration: string | null;        // "1 hour 15 minutes"
  badges: string[];               // ["Best Seller", "Likely to Sell Out", ...]
  url: string;                    // absolute detail URL, no query params
  captured_at: string;            // ISO UTC datetime
  source_listing: string;         // the listing page this card was scraped from
}
```

### Loading in the frontend

**Option A — import the JSON file directly (Vite / Next.js)**

```ts
import viatorTours from "@/data/viator_sagrada_tours.json";

const tours: ViatorTourCard[] = viatorTours as ViatorTourCard[];
```

Copy the generated `viator_sagrada_tours.json` into your `public/` or `src/data/` folder and re-run the scraper whenever you need a fresh snapshot.

**Option B — serve via a thin API endpoint**

Add a FastAPI route that returns the JSON file as-is:

```python
# api/routers/viator_static.py
from pathlib import Path
import json
from fastapi import APIRouter, HTTPException

router = APIRouter()
_DATA_FILE = Path("viator_sagrada_tours.json")

@router.get("/viator/listing", tags=["viator"])
def get_viator_listing():
    if not _DATA_FILE.exists():
        raise HTTPException(404, "No Viator snapshot found. Run the scraper first.")
    return json.loads(_DATA_FILE.read_text(encoding="utf-8"))
```

Then fetch it on the frontend:

```ts
export async function getViatorListing(): Promise<ViatorTourCard[]> {
  const res = await fetch(`${API_BASE_URL}/viator/listing`);
  if (!res.ok) throw new Error(`GET /viator/listing failed: ${res.status}`);
  return res.json();
}
```

### UI mapping suggestion

| UI element | Source field |
|---|---|
| Tour title | `name` |
| Price pill | `price_eur` → `Number(price_eur)` formatted as `€XX` |
| Star rating | `rating` → `Number(rating)` |
| Review count | `reviews` → `Number(reviews).toLocaleString()` |
| Duration chip | `duration` |
| Badge chips | `badges[]` (Best Seller, Likely to Sell Out…) |
| "View on Viator" link | `url` |
| Snapshot age warning | `captured_at` — warn if older than 24 h |

---

## Backend files that define this contract

- `api/routers/market.py`
- `api/schemas/market.py`
- `database/repositories/market_read_repository.py`
- `core/config/settings.py`
- `api/main.py`
- `scraping/viator/listing_scraper.py`
