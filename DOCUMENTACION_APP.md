# Documentacion de la App - OTA Competitive Intelligence Platform

## 1. Que es esta app

`OTA Competitive Intelligence Platform` es una plataforma para capturar y consultar datos de tours en OTAs (principalmente GetYourGuide y Viator), enfocada en:

- Precios por fecha/slot/opcion.
- Disponibilidad por fecha/slot/opcion.
- Comparativa y monitoreo historico para tours canonicos internos.

La app combina:

- Scrapers (Playwright)
- Ingestion a PostgreSQL (SQLAlchemy async)
- API REST (FastAPI)
- Scheduler (APScheduler)

## 2. Arquitectura general

Flujo principal:

1. El scheduler ejecuta jobs periodicos por OTA.
2. Cada job scrapea fuentes configuradas en variables de entorno.
3. El resultado se persiste en tablas `prices` y `availability`.
4. La API expone snapshots y vistas agregadas para frontend/analitica.

Modulos principales:

- `api/`: API REST v1 y esquemas de respuesta.
- `scheduler/`: ejecucion periodica de scraping.
- `scraping/`: implementacion de scrapers por OTA.
- `core/services/`: upsert de tours/sources y persistencia de scrape.
- `database/models/`: entidades SQLAlchemy.
- `database/repositories/`: consultas de lectura para mercado/API.

## 3. Stack tecnico

- Python 3.12+
- FastAPI
- SQLAlchemy async + asyncpg
- PostgreSQL
- Alembic
- APScheduler
- Playwright
- Docker Compose

## 4. Configuracion por entorno (.env)

Variables clave:

- `APP_ENV`
- `LOG_LEVEL`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_PORT`
- `DATABASE_URL`
- `API_HOST`
- `API_PORT`
- `FRONTEND_ORIGINS`
- `SCHEDULER_TZ`
- `SCHEDULER_CRON`
- `SCHEDULER_RUN_ON_STARTUP`
- `GYG_MONITORED_TOURS_JSON`
- `GYG_DAILY_HORIZON_DAYS`
- `MONITORED_TOURS_JSON`
- `VIATOR_MONITORED_TOURS_JSON`
- `VIATOR_SCHEDULER_CRON`

Ejemplo de item para `GYG_MONITORED_TOURS_JSON` / `VIATOR_MONITORED_TOURS_JSON`:

```json
[
  {
    "internal_code": "SAGRADA_REGULAR_LARGE",
    "attraction": "Sagrada Familia",
    "variant": "Regular / Large groups",
    "source_url": "https://www.getyourguide.es/sagrada-familia-l2699/",
    "external_product_id": "sagrada-familia-l2699",
    "city": "Barcelona",
    "market": "ES"
  }
]
```

Ejemplo de item para `MONITORED_TOURS_JSON` (seed de mapeos OTA):

```json
[
  {
    "internal_code": "SAGRADA_REGULAR_LARGE",
    "attraction": "Sagrada Familia",
    "variant": "Regular / Large groups",
    "ota_name": "getyourguide",
    "external_product_id": "sagrada-familia-l2699",
    "source_url": "https://www.getyourguide.es/sagrada-familia-l2699/",
    "city": "Barcelona",
    "market": "ES"
  }
]
```

## 5. Modelo de datos

### 5.1 `tours`

Entidad canonica interna.

Campos relevantes:

- `id` (UUID)
- `internal_code` (unico)
- `attraction`
- `variant`
- `city`
- `market`
- `is_active`

### 5.2 `ota_sources`

Relaciona un tour interno con un producto externo en una OTA.

Campos relevantes:

- `id` (UUID)
- `tour_id` (FK a `tours`)
- `ota_name` (ej: `getyourguide`, `viator`)
- `external_product_id`
- `product_url`
- `default_currency`
- `default_locale`
- `is_active`
- `source_metadata` (JSONB)

Restriccion unica:

- (`ota_name`, `external_product_id`)

### 5.3 `prices`

Snapshot de precio observado.

Campos relevantes:

- `id` (bigint)
- `ota_source_id` (FK)
- `scrape_run_id` (UUID)
- `observed_at`
- `target_date`
- `horizon_days` (0..180)
- `slot_time`
- `language_code`
- `option_name`
- `currency_code`
- `list_price`
- `final_price`
- `raw_payload` (JSONB)

### 5.4 `availability`

Snapshot de disponibilidad observado.

Campos relevantes:

- `id` (bigint)
- `ota_source_id` (FK)
- `scrape_run_id` (UUID)
- `observed_at`
- `target_date`
- `horizon_days` (0..180)
- `slot_time`
- `language_code`
- `option_name`
- `is_available`
- `seats_available`
- `raw_payload` (JSONB)

## 6. Ingestion de datos

Servicio: `core/services/scrape_ingestion.py`.

Procesos clave:

1. `upsert_tour_and_source(...)`
: crea/actualiza tour y source si no existen.
2. `persist_scrape_result(...)`
: inserta `Price` y `Availability` para un `scrape_run_id` comun y hace `commit`.

Notas:

- Cada ciclo de scrape genera nuevos snapshots historicos.
- `raw_payload` conserva metadatos utiles para analisis y UI.

## 7. Scheduler

Entrypoint: `python -m scheduler.runner`.

### 7.1 Jobs programados

- `run_getyourguide_cycle` con cron `SCHEDULER_CRON`
- `run_viator_cycle` con cron `VIATOR_SCHEDULER_CRON`

Comportamiento:

- `max_instances=1` para evitar solapamientos.
- `coalesce=True` para consolidar ejecuciones atrasadas.
- Si `SCHEDULER_RUN_ON_STARTUP=true`, dispara un ciclo inmediato al iniciar.

### 7.2 Job GetYourGuide

Archivo: `scheduler/jobs/getyourguide_job.py`.

- Lee `GYG_MONITORED_TOURS_JSON`.
- Calcula horizontes usando `GYG_DAILY_HORIZON_DAYS` (cap 180).
- Scrapea por horizonte y persiste parcial por cada fecha.

### 7.3 Job Viator

Archivo: `scheduler/jobs/viator_job.py`.

- Lee `VIATOR_MONITORED_TOURS_JSON`.
- Usa `ViatorListingScraper(headless=False)` por bloqueo Cloudflare.
- Mapea cards del listing a puntos de precio/disponibilidad con `horizon_days=0`.

## 8. Scrapers

### 8.1 GetYourGuide

- Runner manual: `python -m scraping.getyourguide.runner <source_url>`
- Scraper principal: `scraping/getyourguide/scraper.py`

### 8.2 Viator

- Runner detalle/listing: `python -m scraping.viator.runner <listing_url> --days 3`
- Listing scraper (snapshot JSON): `python -m scraping.viator.listing_scraper --no-headless --out data/viator_tours.json`

El endpoint de API `/api/v1/viator/listing` sirve este archivo JSON para frontend.

## 9. API REST

Base URL local tipica:

- `http://localhost:8001/api/v1` (si API en Docker con `API_PORT=8001`)
- `http://localhost:8000/api/v1` (si API local con uvicorn en 8000)

Documentacion OpenAPI:

- `http://localhost:8001/docs` o `http://localhost:8000/docs`

### 9.1 Health

- `GET /health`
- `GET /health/db`

### 9.2 Mercado / monitoreo

- `GET /tours`
- `GET /sources?tour_code=...`
- `GET /prices/latest?tour_code=...&horizon_days=...|range_days=...&ota_name=...&limit=...`
- `GET /availability/latest?tour_code=...&horizon_days=...|range_days=...&ota_name=...&limit=...`
- `GET /availability/heatmap?tour_code=...&range_days=...|from_date=...&to_date=...&ota_name=...`
- `GET /availability/day-detail?tour_code=...&target_date=...&ota_name=...`
- `GET /prices/timeseries?tour_code=...&horizon_days=...&from_date=...&to_date=...&limit=...`

### 9.3 Viator snapshot

- `GET /viator/listing`

Devuelve 404 si no existe `data/viator_tours.json`.

## 10. Logica de snapshots en consultas

Repositorio: `database/repositories/market_read_repository.py`.

Puntos importantes:

- `latest_*_snapshot` colapsa filas para devolver la observacion mas reciente por clave logica.
- Clave exacta: `source + target_date + horizon + option + language + slot_time`.
- Si hay slots con hora (`slot_time`), se priorizan esos; si no, cae al ultimo registro sin hora.
- Soporta filtro por `tour_code`, `ota_name`, horizonte y rango de fechas.

## 11. Ejecucion recomendada en local

Referencia rapida (detallada en `GUIA_INSTALACION_Y_ARRANQUE.md`):

1. Copiar `.env.example` a `.env`.
2. Levantar Postgres: `docker compose up -d postgres`.
3. Migrar: `alembic upgrade head`.
4. Seed mappings: `python -m scripts.seed_monitored_tours`.
5. Levantar stack: `docker compose up --build`.

## 12. Estructura de carpetas (alto nivel)

```text
api/                # FastAPI routers, schemas, deps
core/               # config, logging, services
database/           # models, migrations, repos, session
scheduler/          # jobs y runner APScheduler
scraping/           # scrapers por OTA
scripts/            # utilidades (seed, debug)
analytics/          # pipelines/reportes
tests/              # unit, integration, e2e
```

## 13. Estado funcional actual

- API de consulta operativa para tours/sources/precios/disponibilidad.
- Heatmap y drill-down de disponibilidad disponibles.
- Pipeline scheduler para GetYourGuide y Viator.
- Persistencia historica en PostgreSQL con migraciones Alembic.
- Endpoint para snapshot de listing de Viator disponible para frontend.

## 14. Documentos relacionados

- Instalacion y arranque: `GUIA_INSTALACION_Y_ARRANQUE.md`
- Integracion frontend/API: `FRONTEND_INTEGRATION.md`
- Referencia de modelos DB: `database/models/README.md`
