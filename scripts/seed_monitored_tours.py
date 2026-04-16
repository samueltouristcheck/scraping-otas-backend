from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, ValidationError
from sqlalchemy import select

from core.config import get_settings
from core.logging import configure_logging
from core.services import upsert_tour_and_source
from database.models import Tour
from database.session import session_factory


class SeedSourceMapping(BaseModel):
    internal_code: str = Field(..., min_length=3, max_length=120)
    attraction: str = Field(..., min_length=2, max_length=100)
    variant: str = Field(..., min_length=2, max_length=100)
    ota_name: str = Field(..., min_length=3, max_length=30)
    external_product_id: str = Field(..., min_length=2, max_length=200)
    source_url: HttpUrl
    city: str = Field(default="Barcelona", max_length=100)
    market: str = Field(default="ES", max_length=10)


DEFAULT_TOURS: list[dict[str, Any]] = [
    {
        "internal_code": "SAGRADA_REGULAR_LARGE",
        "attraction": "Sagrada Familia",
        "variant": "Regular / Large groups",
        "city": "Barcelona",
        "market": "ES",
    },
    {
        "internal_code": "SAGRADA_SEMI_SMALL",
        "attraction": "Sagrada Familia",
        "variant": "Semi / Small groups",
        "city": "Barcelona",
        "market": "ES",
    },
    {
        "internal_code": "PARK_GUELL_REGULAR",
        "attraction": "Park Güell",
        "variant": "Regular tours",
        "city": "Barcelona",
        "market": "ES",
    },
]


def _monitored_json_from_settings(settings: Any) -> str:
    raw = (settings.monitored_tours_json or "").strip()
    if raw and raw != "[]":
        return raw
    default_path = Path(__file__).resolve().parent.parent / "config" / "monitored_tours_seed.json"
    if default_path.is_file():
        return default_path.read_text(encoding="utf-8")
    return raw


def parse_seed_sources(raw_json: str) -> list[SeedSourceMapping]:
    if not raw_json.strip():
        return []

    payload = json.loads(raw_json)
    if not isinstance(payload, list):
        raise ValueError("MONITORED_TOURS_JSON must be a JSON array")

    parsed: list[SeedSourceMapping] = []
    for item in payload:
        parsed.append(SeedSourceMapping.model_validate(item))
    return parsed


async def run_seed() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    mappings = parse_seed_sources(_monitored_json_from_settings(settings))

    canonical_by_code = {item["internal_code"]: item for item in DEFAULT_TOURS}

    async with session_factory() as session:
        for canonical in DEFAULT_TOURS:
            stmt = select(Tour).where(Tour.internal_code == canonical["internal_code"])
            existing = await session.scalar(stmt)
            if existing is None:
                session.add(
                    Tour(
                        attraction=canonical["attraction"],
                        variant=canonical["variant"],
                        internal_code=canonical["internal_code"],
                        city=canonical["city"],
                        market=canonical["market"],
                        is_active=True,
                    )
                )

        # Sin flush, el siguiente bucle no ve los tours recién añadidos y upsert intenta duplicar internal_code.
        await session.flush()

        for source in mappings:
            canonical = canonical_by_code.get(source.internal_code)
            if canonical is None:
                canonical = {
                    "internal_code": source.internal_code,
                    "attraction": source.attraction,
                    "variant": source.variant,
                    "city": source.city,
                    "market": source.market,
                }

            from models.dto.monitoring import MonitoredTourSource

            monitored_source = MonitoredTourSource(
                internal_code=canonical["internal_code"],
                attraction=canonical["attraction"],
                variant=canonical["variant"],
                source_url=source.source_url,
                external_product_id=source.external_product_id,
                city=canonical["city"],
                market=canonical["market"],
            )

            await upsert_tour_and_source(
                session=session,
                source_cfg=monitored_source,
                ota_name=source.ota_name.lower(),
            )

        await session.commit()


def main() -> None:
    try:
        asyncio.run(run_seed())
    except ValidationError as exc:
        raise SystemExit(f"Invalid MONITORED_TOURS_JSON payload: {exc}") from exc


if __name__ == "__main__":
    main()
