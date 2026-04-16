from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, Field, HttpUrl


class HorizonRequest(BaseModel):
    horizon_days: int = Field(..., ge=0)
    target_date: date


class ScrapedPricePoint(BaseModel):
    target_date: date
    horizon_days: int
    observed_at: datetime
    slot_time: time | None = None
    language_code: str | None = None
    option_name: str | None = None
    currency_code: str = "EUR"
    list_price: Decimal
    final_price: Decimal | None = None
    popularity_count_yesterday: int | None = None
    popularity_label: str | None = None
    # Normalised title of the GYG detail page this option belongs to.
    # Used to cross-link option cards back to the parent product listing.
    detail_tour_name: str | None = None
    # Canonical GetYourGuide product URL (path only, no date query) for this option.
    detail_page_url: str | None = None


class ScrapedAvailabilityPoint(BaseModel):
    target_date: date
    horizon_days: int
    observed_at: datetime
    slot_time: time | None = None
    language_code: str | None = None
    option_name: str | None = None
    is_available: bool
    seats_available: int | None = None
    # Normalised title of the GYG detail page this option belongs to.
    detail_tour_name: str | None = None
    detail_page_url: str | None = None


class ScrapeResult(BaseModel):
    ota_name: str
    source_url: HttpUrl
    product_name: str | None = None
    captured_at: datetime
    languages: list[str] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)
    slots: list[time] = Field(default_factory=list)
    prices: list[ScrapedPricePoint] = Field(default_factory=list)
    availability: list[ScrapedAvailabilityPoint] = Field(default_factory=list)
    raw_excerpt: str | None = None
