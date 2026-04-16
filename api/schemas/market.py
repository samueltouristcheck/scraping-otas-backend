from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, HttpUrl


class TourResponse(BaseModel):
    id: UUID
    internal_code: str
    attraction: str
    variant: str
    city: str
    market: str
    is_active: bool


class SourceResponse(BaseModel):
    id: UUID
    tour_id: UUID
    ota_name: str
    external_product_id: str
    product_url: HttpUrl
    default_currency: str
    default_locale: str
    is_active: bool


class PricePointResponse(BaseModel):
    id: int
    ota_source_id: UUID
    ota_name: str | None
    target_date: date
    horizon_days: int
    slot_time: time | None
    language_code: str | None
    option_name: str | None
    detail_tour_name: str | None = None
    detail_page_url: str | None = None
    currency_code: str
    list_price: Decimal
    final_price: Decimal | None
    popularity_count_yesterday: int | None
    popularity_label: str | None
    observed_at: datetime


class AvailabilityPointResponse(BaseModel):
    id: int
    ota_source_id: UUID
    ota_name: str | None
    target_date: date
    horizon_days: int
    slot_time: time | None
    language_code: str | None
    option_name: str | None
    detail_tour_name: str | None = None
    is_available: bool
    seats_available: int | None
    observed_at: datetime


class LatestPricesResponse(BaseModel):
    tour_code: str
    observed_at: datetime | None
    items: list[PricePointResponse]


class LatestAvailabilityResponse(BaseModel):
    tour_code: str
    observed_at: datetime | None
    items: list[AvailabilityPointResponse]


class PriceTimeseriesResponse(BaseModel):
    tour_code: str
    items: list[PricePointResponse]


class HeatmapDayResponse(BaseModel):
    target_date: date
    level: str
    availability_rate: float
    available_slots: int
    total_slots: int
    avg_final_price: Decimal | None
    currency_code: str | None


class AvailabilityKpiResponse(BaseModel):
    availability_rate_7d: float
    availability_rate_30d: float
    sold_out_days: int
    critical_slots: int
    wow_current_week_rate: float
    wow_previous_week_rate: float
    wow_delta: float


class AvailabilityHeatmapResponse(BaseModel):
    tour_code: str
    ota_name: str | None
    from_date: date
    to_date: date
    observed_at: datetime | None
    kpis: AvailabilityKpiResponse
    days: list[HeatmapDayResponse]


class AvailabilityDaySlotResponse(BaseModel):
    target_date: date
    slot_time: time | None
    is_available: bool
    seats_available: int | None
    ota_name: str | None
    option_name: str | None
    detail_tour_name: str | None = None
    language_code: str | None
    final_price: Decimal | None
    list_price: Decimal | None
    currency_code: str | None
    popularity_count_yesterday: int | None
    popularity_label: str | None
    observed_at: datetime


class AvailabilityDayDetailResponse(BaseModel):
    tour_code: str
    ota_name: str | None
    target_date: date
    observed_at: datetime | None
    slots: list[AvailabilityDaySlotResponse]
