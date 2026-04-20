from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    frontend_origins_csv: str = Field(default="http://localhost:3000,http://localhost:5173", alias="FRONTEND_ORIGINS")

    postgres_db: str = Field(default="ota_intel", alias="POSTGRES_DB")
    postgres_user: str = Field(default="ota_user", alias="POSTGRES_USER")
    postgres_password: str = Field(default="ota_password", alias="POSTGRES_PASSWORD")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")

    database_url: str = Field(
        default="postgresql+asyncpg://ota_user:ota_password@localhost:5432/ota_intel",
        alias="DATABASE_URL",
    )

    scheduler_tz: str = Field(default="Europe/Madrid", alias="SCHEDULER_TZ")
    scheduler_cron: str = Field(default="0 */2 * * *", alias="SCHEDULER_CRON")
    scheduler_run_on_startup: bool = Field(default=False, alias="SCHEDULER_RUN_ON_STARTUP")

    gyg_monitored_tours_json: str = Field(default="[]", alias="GYG_MONITORED_TOURS_JSON")
    gyg_daily_horizon_days: int = Field(default=180, alias="GYG_DAILY_HORIZON_DAYS")
    # Si True: solo scrapea fechas de visita futuras (ver gyg_forward_*). Si False: usa gyg_daily_horizon_days desde hoy.
    gyg_future_only: bool = Field(default=True, alias="GYG_FUTURE_ONLY")
    # Primer día de visita a scrapear: 0=hoy, 1=mañana (recomendado si no quieres "hoy" en el listado).
    gyg_forward_start_offset_days: int = Field(default=1, alias="GYG_FORWARD_START_OFFSET_DAYS")
    # Cuántos días de visita consecutivos scrapear hacia adelante (p. ej. 14 = ~dos semanas desde el offset).
    gyg_forward_window_days: int = Field(default=14, alias="GYG_FORWARD_WINDOW_DAYS")
    monitored_tours_json: str = Field(default="[]", alias="MONITORED_TOURS_JSON")

    viator_monitored_tours_json: str = Field(default="[]", alias="VIATOR_MONITORED_TOURS_JSON")
    viator_scheduler_cron: str = Field(default="0 */2 * * *", alias="VIATOR_SCHEDULER_CRON")
    # True = navegador sin UI (Docker/Render). False = ventana visible; a veces evita Cloudflare en local.
    viator_headless: bool = Field(default=False, alias="VIATOR_HEADLESS")

    # Mismo valor que VITE_SCRAPING_TRIGGER_TOKEN en el frontend (cabecera X-Scraping-Token). Vacío = endpoint desactivado.
    scraping_trigger_secret: str | None = Field(default=None, alias="SCRAPING_TRIGGER_SECRET")

    @property
    def frontend_origins(self) -> list[str]:
        return [item.strip() for item in self.frontend_origins_csv.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
