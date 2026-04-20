from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import db_session_dependency
from api.schemas import (
    AvailabilityDayDetailResponse,
    AvailabilityDaySlotResponse,
    AvailabilityKpiResponse,
    AvailabilityPointResponse,
    AvailabilityHeatmapResponse,
    HeatmapDayResponse,
    LatestAvailabilityResponse,
    LatestPricesResponse,
    PricePointResponse,
    PriceTimeseriesResponse,
    SourceResponse,
    TourResponse,
)
from database.repositories import MarketReadRepository

router = APIRouter(tags=["market"])


async def _source_name_map(repository: MarketReadRepository, source_ids: list[UUID]) -> dict[UUID, str]:
    return await repository.source_names_by_ids(set(source_ids))


@router.get("/tours", response_model=list[TourResponse], summary="List monitored tours")
async def get_tours(
    session: AsyncSession = Depends(db_session_dependency),
) -> list[TourResponse]:
    repository = MarketReadRepository(session)
    tours = await repository.list_tours()
    return [
        TourResponse(
            id=tour.id,
            internal_code=tour.internal_code,
            attraction=tour.attraction,
            variant=tour.variant,
            city=tour.city,
            market=tour.market,
            is_active=tour.is_active,
        )
        for tour in tours
    ]


@router.get("/sources", response_model=list[SourceResponse], summary="List OTA sources for a tour")
async def get_sources(
    tour_code: str = Query(..., min_length=3),
    session: AsyncSession = Depends(db_session_dependency),
) -> list[SourceResponse]:
    repository = MarketReadRepository(session)
    sources = await repository.list_sources(tour_code=tour_code)

    return [
        SourceResponse(
            id=source.id,
            tour_id=source.tour_id,
            ota_name=source.ota_name,
            external_product_id=source.external_product_id,
            product_url=source.product_url,
            default_currency=source.default_currency,
            default_locale=source.default_locale,
            is_active=source.is_active,
        )
        for source in sources
    ]


@router.get("/prices/latest", response_model=LatestPricesResponse, summary="Get latest price snapshot")
async def get_latest_prices(
    tour_code: str = Query(..., min_length=3),
    ota_name: str | None = Query(default=None),
    horizon_days: int | None = Query(default=None, ge=0),
    range_days: int | None = Query(default=None, ge=0),
    limit: int | None = Query(default=None, ge=1, le=50000),
    session: AsyncSession = Depends(db_session_dependency),
) -> LatestPricesResponse:
    repository = MarketReadRepository(session)
    title_contains = await repository.attraction_by_tour_code(tour_code)
    target_date_from: date | None = None
    target_date_to: date | None = None
    if range_days is not None:
        today = datetime.now(UTC).date()
        target_date_from = today
        target_date_to = today + timedelta(days=max(range_days - 1, 0))
        horizon_days = None

    effective_limit = limit
    if effective_limit is None:
        effective_limit = 50000 if range_days is not None else 500

    observed_at, rows = await repository.latest_prices_snapshot(
        tour_code=tour_code,
        ota_name=ota_name,
        title_contains=title_contains,
        horizon_days=horizon_days,
        target_date_from=target_date_from,
        target_date_to=target_date_to,
        limit=effective_limit,
    )

    source_cache = await _source_name_map(repository, [row.ota_source_id for row in rows])
    items: list[PricePointResponse] = []
    for row in rows:
        rp = row.raw_payload or {}
        items.append(
            PricePointResponse(
                id=row.id,
                ota_source_id=row.ota_source_id,
                ota_name=source_cache.get(row.ota_source_id),
                target_date=row.target_date,
                horizon_days=row.horizon_days,
                slot_time=row.slot_time,
                language_code=row.language_code,
                option_name=row.option_name,
                detail_tour_name=rp.get("detail_tour_name"),
                detail_page_url=rp.get("detail_page_url"),
                currency_code=row.currency_code,
                list_price=row.list_price,
                final_price=row.final_price,
                popularity_count_yesterday=rp.get("popularity_count_yesterday"),
                popularity_label=rp.get("popularity_label"),
                observed_at=row.observed_at,
            )
        )

    return LatestPricesResponse(tour_code=tour_code, observed_at=observed_at, items=items)


@router.get(
    "/availability/latest",
    response_model=LatestAvailabilityResponse,
    summary="Get latest availability snapshot",
)
async def get_latest_availability(
    tour_code: str = Query(..., min_length=3),
    ota_name: str | None = Query(default=None),
    horizon_days: int | None = Query(default=None, ge=0),
    range_days: int | None = Query(default=None, ge=0),
    limit: int | None = Query(default=None, ge=1, le=50000),
    session: AsyncSession = Depends(db_session_dependency),
) -> LatestAvailabilityResponse:
    repository = MarketReadRepository(session)
    title_contains = await repository.attraction_by_tour_code(tour_code)
    target_date_from: date | None = None
    target_date_to: date | None = None
    if range_days is not None:
        today = datetime.now(UTC).date()
        target_date_from = today
        target_date_to = today + timedelta(days=max(range_days - 1, 0))
        horizon_days = None

    effective_limit = limit
    if effective_limit is None:
        effective_limit = 50000 if range_days is not None else 500

    observed_at, rows = await repository.latest_availability_snapshot(
        tour_code=tour_code,
        ota_name=ota_name,
        title_contains=title_contains,
        horizon_days=horizon_days,
        target_date_from=target_date_from,
        target_date_to=target_date_to,
        limit=effective_limit,
    )

    source_cache = await _source_name_map(repository, [row.ota_source_id for row in rows])
    items: list[AvailabilityPointResponse] = []
    for row in rows:
        items.append(
            AvailabilityPointResponse(
                id=row.id,
                ota_source_id=row.ota_source_id,
                ota_name=source_cache.get(row.ota_source_id),
                target_date=row.target_date,
                horizon_days=row.horizon_days,
                slot_time=row.slot_time,
                language_code=row.language_code,
                option_name=row.option_name,
                detail_tour_name=(row.raw_payload or {}).get("detail_tour_name"),
                is_available=row.is_available,
                seats_available=row.seats_available,
                observed_at=row.observed_at,
            )
        )

    return LatestAvailabilityResponse(tour_code=tour_code, observed_at=observed_at, items=items)


def _level_from_rate(rate: float, total_slots: int) -> str:
    if total_slots <= 0:
        return "no-data"
    if rate >= 0.7:
        return "high"
    if rate >= 0.4:
        return "medium"
    return "low"


def _rate(items: list[AvailabilityPointResponse]) -> float:
    if not items:
        return 0.0
    available = sum(1 for item in items if item.is_available)
    return round(available / len(items), 4)


@router.get(
    "/availability/heatmap",
    response_model=AvailabilityHeatmapResponse,
    summary="Monthly availability heatmap overview",
)
async def get_availability_heatmap(
    tour_code: str = Query(..., min_length=3),
    ota_name: str | None = Query(default=None),
    range_days: int | None = Query(default=None, ge=0),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    session: AsyncSession = Depends(db_session_dependency),
) -> AvailabilityHeatmapResponse:
    repository = MarketReadRepository(session)
    title_contains = await repository.attraction_by_tour_code(tour_code)

    today = datetime.now(UTC).date()
    selected_from = from_date or today
    if to_date is not None:
        selected_to = to_date
    elif range_days is not None:
        selected_to = selected_from + timedelta(days=range_days)
    else:
        selected_to = selected_from + timedelta(days=30)

    observed_at, rows = await repository.latest_availability_snapshot(
        tour_code=tour_code,
        ota_name=ota_name,
        title_contains=title_contains,
        target_date_from=selected_from,
        target_date_to=selected_to,
        limit=50000,
    )

    _, price_rows = await repository.latest_prices_snapshot(
        tour_code=tour_code,
        ota_name=ota_name,
        title_contains=title_contains,
        target_date_from=selected_from,
        target_date_to=selected_to,
        limit=50000,
    )

    price_by_day: dict[date, list[Decimal]] = {}
    currency_by_day: dict[date, str | None] = {}
    for price_row in price_rows:
        price_by_day.setdefault(price_row.target_date, []).append(price_row.final_price or price_row.list_price)
        if price_row.target_date not in currency_by_day:
            currency_by_day[price_row.target_date] = price_row.currency_code

    source_cache = await _source_name_map(repository, [row.ota_source_id for row in rows])
    mapped_items: list[AvailabilityPointResponse] = []
    for row in rows:
        mapped_items.append(
            AvailabilityPointResponse(
                id=row.id,
                ota_source_id=row.ota_source_id,
                ota_name=source_cache.get(row.ota_source_id),
                target_date=row.target_date,
                horizon_days=row.horizon_days,
                slot_time=row.slot_time,
                language_code=row.language_code,
                option_name=row.option_name,
                is_available=row.is_available,
                seats_available=row.seats_available,
                observed_at=row.observed_at,
            )
        )

    by_day: dict[date, list[AvailabilityPointResponse]] = {}
    for item in mapped_items:
        by_day.setdefault(item.target_date, []).append(item)

    days: list[HeatmapDayResponse] = []
    for target_day in sorted(by_day.keys()):
        day_items = by_day[target_day]
        total_slots = len(day_items)
        available_slots = sum(1 for item in day_items if item.is_available)
        availability_rate = round((available_slots / total_slots), 4) if total_slots else 0.0
        day_prices = price_by_day.get(target_day, [])
        avg_price = (sum(day_prices) / Decimal(len(day_prices))) if day_prices else None
        days.append(
            HeatmapDayResponse(
                target_date=target_day,
                level=_level_from_rate(availability_rate, total_slots),
                availability_rate=availability_rate,
                available_slots=available_slots,
                total_slots=total_slots,
                avg_final_price=avg_price,
                currency_code=currency_by_day.get(target_day),
            )
        )

    next_7_cutoff = today + timedelta(days=7)
    next_30_cutoff = today + timedelta(days=30)
    window_7 = [item for item in mapped_items if today <= item.target_date <= next_7_cutoff]
    window_30 = [item for item in mapped_items if today <= item.target_date <= next_30_cutoff]

    sold_out_days = 0
    for day_items in by_day.values():
        if day_items and not any(item.is_available for item in day_items):
            sold_out_days += 1

    critical_slots = sum(1 for item in mapped_items if item.slot_time is not None and not item.is_available)

    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    prev_week_start = week_start - timedelta(days=7)
    prev_week_end = week_start - timedelta(days=1)
    current_week = [item for item in mapped_items if week_start <= item.target_date <= week_end]
    previous_week = [item for item in mapped_items if prev_week_start <= item.target_date <= prev_week_end]
    current_week_rate = _rate(current_week)
    previous_week_rate = _rate(previous_week)

    kpis = AvailabilityKpiResponse(
        availability_rate_7d=_rate(window_7),
        availability_rate_30d=_rate(window_30),
        sold_out_days=sold_out_days,
        critical_slots=critical_slots,
        wow_current_week_rate=current_week_rate,
        wow_previous_week_rate=previous_week_rate,
        wow_delta=round(current_week_rate - previous_week_rate, 4),
    )

    return AvailabilityHeatmapResponse(
        tour_code=tour_code,
        ota_name=ota_name,
        from_date=selected_from,
        to_date=selected_to,
        observed_at=observed_at,
        kpis=kpis,
        days=days,
    )


@router.get(
    "/availability/day-detail",
    response_model=AvailabilityDayDetailResponse,
    summary="Availability drill-down by day",
)
async def get_availability_day_detail(
    tour_code: str = Query(..., min_length=3),
    target_date: date = Query(...),
    ota_name: str | None = Query(default=None),
    session: AsyncSession = Depends(db_session_dependency),
) -> AvailabilityDayDetailResponse:
    repository = MarketReadRepository(session)
    title_contains = await repository.attraction_by_tour_code(tour_code)

    observed_at, availability_rows = await repository.latest_availability_snapshot(
        tour_code=tour_code,
        ota_name=ota_name,
        title_contains=title_contains,
        target_date_from=target_date,
        target_date_to=target_date,
        limit=50000,
    )

    _, price_rows = await repository.latest_prices_snapshot(
        tour_code=tour_code,
        ota_name=ota_name,
        title_contains=title_contains,
        target_date_from=target_date,
        target_date_to=target_date,
        limit=50000,
    )

    price_map: dict[tuple[UUID, date, int, object, str | None, str | None], object] = {}
    for price_row in price_rows:
        key = (
            price_row.ota_source_id,
            price_row.target_date,
            price_row.horizon_days,
            price_row.slot_time,
            price_row.language_code,
            price_row.option_name,
        )
        price_map[key] = price_row

    source_cache = await _source_name_map(repository, [row.ota_source_id for row in availability_rows])
    slots: list[AvailabilityDaySlotResponse] = []
    for row in availability_rows:
        key = (
            row.ota_source_id,
            row.target_date,
            row.horizon_days,
            row.slot_time,
            row.language_code,
            row.option_name,
        )
        price_row = price_map.get(key)

        slots.append(
            AvailabilityDaySlotResponse(
                target_date=row.target_date,
                slot_time=row.slot_time,
                is_available=row.is_available,
                seats_available=row.seats_available,
                ota_name=source_cache.get(row.ota_source_id),
                option_name=row.option_name,
                detail_tour_name=(row.raw_payload or {}).get("detail_tour_name"),
                language_code=row.language_code,
                final_price=price_row.final_price if price_row is not None else None,
                list_price=price_row.list_price if price_row is not None else None,
                currency_code=price_row.currency_code if price_row is not None else None,
                popularity_count_yesterday=(price_row.raw_payload or {}).get("popularity_count_yesterday")
                if price_row is not None
                else None,
                popularity_label=(price_row.raw_payload or {}).get("popularity_label") if price_row is not None else None,
                observed_at=row.observed_at,
            )
        )

    slots.sort(key=lambda item: ((item.slot_time is None), item.slot_time or datetime.now(UTC).time(), item.option_name or ""))

    return AvailabilityDayDetailResponse(
        tour_code=tour_code,
        ota_name=ota_name,
        target_date=target_date,
        observed_at=observed_at,
        slots=slots,
    )


@router.get("/prices/timeseries", response_model=PriceTimeseriesResponse, summary="Get price history")
async def get_price_timeseries(
    tour_code: str = Query(..., min_length=3),
    horizon_days: int | None = Query(default=None, ge=0),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    limit: int = Query(default=50_000, ge=1, le=100_000),
    session: AsyncSession = Depends(db_session_dependency),
) -> PriceTimeseriesResponse:
    repository = MarketReadRepository(session)
    rows = await repository.price_timeseries(
        tour_code=tour_code,
        horizon_days=horizon_days,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )

    source_cache = await _source_name_map(repository, [row.ota_source_id for row in rows])
    items: list[PricePointResponse] = []
    for row in rows:
        rp = row.raw_payload or {}
        items.append(
            PricePointResponse(
                id=row.id,
                ota_source_id=row.ota_source_id,
                ota_name=source_cache.get(row.ota_source_id),
                target_date=row.target_date,
                horizon_days=row.horizon_days,
                slot_time=row.slot_time,
                language_code=row.language_code,
                option_name=row.option_name,
                detail_tour_name=rp.get("detail_tour_name"),
                detail_page_url=rp.get("detail_page_url"),
                currency_code=row.currency_code,
                list_price=row.list_price,
                final_price=row.final_price,
                popularity_count_yesterday=rp.get("popularity_count_yesterday"),
                popularity_label=rp.get("popularity_label"),
                observed_at=row.observed_at,
            )
        )

    return PriceTimeseriesResponse(tour_code=tour_code, items=items)
