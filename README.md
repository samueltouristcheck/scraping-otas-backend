# OTA Competitive Intelligence Platform

Production-oriented platform to scrape and track guided tour prices, availability, languages, and options across OTAs.

## Stack
- Python 3.12+
- FastAPI
- Playwright (async)
- PostgreSQL
- SQLAlchemy async
- APScheduler
- Docker Compose

## Bootstrap
1. Copy env file:
   - `copy .env.example .env` (Windows)
2. Provide source mappings in `.env`:
   - `MONITORED_TOURS_JSON` with OTA URLs/product IDs
   - `GYG_MONITORED_TOURS_JSON` for scheduler GetYourGuide job
3. Start DB:
   - `docker compose up -d postgres`
4. Run migrations:
   - `alembic upgrade head`
5. Seed canonical tours and OTA mappings:
   - `python -m scripts.seed_monitored_tours`
6. Start full stack:
   - `docker compose up --build`

## Run API only (local frontend on port 5173)
Use this flow when you only need backend + DB and want the API on `http://localhost:8001`.

1. Ensure Docker Desktop is running.
2. Start DB + API containers:
   - `docker compose up -d postgres api`
3. Validate API:
   - `http://127.0.0.1:8001/api/v1/health`
   - `http://127.0.0.1:8001/api/v1/health/db`
   - `http://127.0.0.1:8001/api/v1/tours`

Expected result:
- `/health` returns `{"status":"ok"...}`
- `/health/db` returns `{"status":"ok","database":"reachable"}`

## Troubleshooting (Windows + Docker)
If you get:
- `open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`

It means the Docker engine is not running yet.

1. Open Docker Desktop and wait until it is fully started.
2. Confirm with:
   - `docker info`
3. Retry:
   - `docker compose up -d postgres api`

## Notes
- Migrations are in `database/migrations`.
- Initial schema revision: `20260302_0001`.
- Scheduler entrypoint: `python -m scheduler.runner`.
