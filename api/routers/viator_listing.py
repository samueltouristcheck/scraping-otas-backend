"""Thin endpoint that serves the Viator listing snapshot JSON file.

The file is produced by::

    python -m scraping.viator.listing_scraper --out viator_tours.json --no-headless

The endpoint simply reads and returns the file contents so the frontend
does not have to bundle or statically import the JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["viator"])

# Default location: project root (where the scraper writes by default).
# Override via the VIATOR_LISTING_FILE env var if you put the file elsewhere.
import os

# Ruta por defecto respecto a la raíz del repo (no depende del directorio desde el que arranques uvicorn).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_VIATOR_JSON = _PROJECT_ROOT / "data" / "viator_tours.json"
_DATA_FILE = Path(os.environ.get("VIATOR_LISTING_FILE", str(_DEFAULT_VIATOR_JSON)))


class ViatorTourCard(BaseModel):
    name: str
    price_eur: str | None
    rating: str | None
    reviews: str | None
    duration: str | None
    badges: list[str]
    url: str
    captured_at: str
    source_listing: str


@router.get(
    "/viator/listing",
    response_model=list[ViatorTourCard],
    summary="Get the latest Viator listing snapshot",
    description=(
        "Returns the JSON file produced by `scraping/viator/listing_scraper.py`. "
        "Returns 404 if the scraper has not been run yet. "
        "Re-run the scraper to refresh the snapshot."
    ),
)
def get_viator_listing() -> list[ViatorTourCard]:
    if not _DATA_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Viator listing snapshot not found at '{_DATA_FILE}'. "
                "Run: python -m scraping.viator.listing_scraper --no-headless"
            ),
        )

    try:
        raw = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read Viator listing file: {exc}",
        ) from exc

    if not isinstance(raw, list):
        raise HTTPException(
            status_code=500,
            detail="Viator listing file has unexpected format (expected a JSON array).",
        )

    return raw
