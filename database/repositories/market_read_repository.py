from __future__ import annotations

import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from database.models import Availability, OtaSource, Price, Tour

# El scraper de Viator (listado) no rellena option_name/detail con el nombre de la atracción como GYG;
# sin esto, title_contains elimina todas las filas viator. Los listados viator siguen acotados por tour_id.
_VIATOR_OTA = "viator"


def _accent_fold_lower(s: str) -> str:
    """Igual que el scraper GYG ``_norm`` sin colapsar espacios: ü → u para poder hacer ``contains`` en SQL."""
    n = unicodedata.normalize("NFKD", s.strip())
    return "".join(c for c in n if not unicodedata.combining(c)).lower()


def _title_contains_search_variants(attraction: str) -> list[str]:
    """``Tour.attraction`` suele llevar tildes; los textos scrapeados a menudo van sin ellas."""
    raw = attraction.strip()
    if not raw:
        return []
    lower_only = raw.lower()
    folded = _accent_fold_lower(raw)
    out: list[str] = []
    for v in {lower_only, folded}:
        if v and v not in out:
            out.append(v)
    return out


class MarketReadRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_tours(self) -> list[Tour]:
        stmt = (
            select(Tour)
            .where(Tour.is_active.is_(True))
            .order_by(Tour.attraction.asc(), Tour.variant.asc())
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def list_sources(self, tour_code: str) -> list[OtaSource]:
        stmt = (
            select(OtaSource)
            .join(Tour, Tour.id == OtaSource.tour_id)
            .where(Tour.internal_code == tour_code, OtaSource.is_active.is_(True))
            .order_by(OtaSource.ota_name.asc(), OtaSource.external_product_id.asc())
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def attraction_by_tour_code(self, tour_code: str) -> str | None:
        stmt = select(Tour.attraction).where(Tour.internal_code == tour_code)
        return await self.session.scalar(stmt)

    async def latest_prices_snapshot(
        self,
        *,
        tour_code: str,
        ota_name: str | None = None,
        title_contains: str | None = None,
        horizon_days: int | None = None,
        target_date_from: date | None = None,
        target_date_to: date | None = None,
        limit: int = 500,
    ) -> tuple[datetime | None, list[Price]]:
        filters = [Tour.internal_code == tour_code]
        if horizon_days is not None:
            # Viator guarda horizon_days=0 en el listado; sigue siendo el snapshot “actual” de esa fuente.
            filters.append(
                or_(
                    Price.horizon_days == horizon_days,
                    and_(OtaSource.ota_name == _VIATOR_OTA, Price.horizon_days == 0),
                )
            )
        if target_date_from is not None and target_date_to is not None:
            # Listado Viator (horizon 0): target_date = día del scrape; puede ser 1–2 días respecto al borde UTC de la API.
            filters.append(
                or_(
                    and_(Price.target_date >= target_date_from, Price.target_date <= target_date_to),
                    and_(
                        OtaSource.ota_name == _VIATOR_OTA,
                        Price.horizon_days == 0,
                        Price.target_date >= target_date_from - timedelta(days=5),
                        Price.target_date <= target_date_to,
                    ),
                )
            )
        else:
            if target_date_from is not None:
                filters.append(Price.target_date >= target_date_from)
            if target_date_to is not None:
                filters.append(Price.target_date <= target_date_to)
        if ota_name is not None:
            filters.append(OtaSource.ota_name == ota_name)
        if title_contains:
            variants = _title_contains_search_variants(title_contains)
            if variants:
                # Match against option_name OR the parent GYG product page title
                # stored in raw_payload->>'detail_tour_name'. This lets callers
                # find all option cards that belong to a specific GYG listing
                # even when the card names differ from the listing title.
                # Viator: las tarjetas del listado no suelen repetir el nombre de la atracción.
                text_conds = []
                for v in variants:
                    text_conds.append(
                        func.lower(func.coalesce(Price.option_name, "")).contains(v),
                    )
                    text_conds.append(
                        func.lower(func.coalesce(Price.raw_payload["detail_tour_name"].astext, "")).contains(v),
                    )
                filters.append(or_(OtaSource.ota_name == _VIATOR_OTA, *text_conds))

        ranked_rows = (
            select(
                Price,
                func.row_number()
                .over(
                    partition_by=(
                        Price.ota_source_id,
                        Price.target_date,
                        Price.horizon_days,
                        Price.option_name,
                        Price.language_code,
                        Price.slot_time,
                    ),
                    order_by=Price.observed_at.desc(),
                )
                .label("row_num"),
            )
            .join(OtaSource, OtaSource.id == Price.ota_source_id)
            .join(Tour, Tour.id == OtaSource.tour_id)
            .where(*filters)
        )
        ranked_subquery = ranked_rows.subquery()
        latest_price = aliased(Price, ranked_subquery)
        rows_stmt = (
            select(latest_price)
            .where(ranked_subquery.c.row_num == 1)
            .order_by(
                latest_price.target_date.asc(),
                latest_price.slot_time.asc().nulls_last(),
                latest_price.option_name.asc().nulls_last(),
                latest_price.observed_at.desc(),
            )
        )
        rows = await self.session.scalars(rows_stmt)
        items = self._collapse_latest_rows(list(rows.all()), limit=limit)
        latest_observed_at = max((row.observed_at for row in items), default=None)
        return latest_observed_at, items

    async def latest_availability_snapshot(
        self,
        *,
        tour_code: str,
        ota_name: str | None = None,
        title_contains: str | None = None,
        horizon_days: int | None = None,
        target_date_from: date | None = None,
        target_date_to: date | None = None,
        limit: int = 500,
    ) -> tuple[datetime | None, list[Availability]]:
        filters = [Tour.internal_code == tour_code]
        if horizon_days is not None:
            filters.append(
                or_(
                    Availability.horizon_days == horizon_days,
                    and_(OtaSource.ota_name == _VIATOR_OTA, Availability.horizon_days == 0),
                )
            )
        if target_date_from is not None and target_date_to is not None:
            filters.append(
                or_(
                    and_(Availability.target_date >= target_date_from, Availability.target_date <= target_date_to),
                    and_(
                        OtaSource.ota_name == _VIATOR_OTA,
                        Availability.horizon_days == 0,
                        Availability.target_date >= target_date_from - timedelta(days=5),
                        Availability.target_date <= target_date_to,
                    ),
                )
            )
        else:
            if target_date_from is not None:
                filters.append(Availability.target_date >= target_date_from)
            if target_date_to is not None:
                filters.append(Availability.target_date <= target_date_to)
        if ota_name is not None:
            filters.append(OtaSource.ota_name == ota_name)
        if title_contains:
            variants = _title_contains_search_variants(title_contains)
            if variants:
                text_conds = []
                for v in variants:
                    text_conds.append(
                        func.lower(func.coalesce(Availability.option_name, "")).contains(v),
                    )
                    text_conds.append(
                        func.lower(
                            func.coalesce(Availability.raw_payload["detail_tour_name"].astext, ""),
                        ).contains(v),
                    )
                filters.append(or_(OtaSource.ota_name == _VIATOR_OTA, *text_conds))

        ranked_rows = (
            select(
                Availability,
                func.row_number()
                .over(
                    partition_by=(
                        Availability.ota_source_id,
                        Availability.target_date,
                        Availability.horizon_days,
                        Availability.option_name,
                        Availability.language_code,
                        Availability.slot_time,
                    ),
                    order_by=Availability.observed_at.desc(),
                )
                .label("row_num"),
            )
            .join(OtaSource, OtaSource.id == Availability.ota_source_id)
            .join(Tour, Tour.id == OtaSource.tour_id)
            .where(*filters)
        )
        ranked_subquery = ranked_rows.subquery()
        latest_availability = aliased(Availability, ranked_subquery)
        rows_stmt = (
            select(latest_availability)
            .where(ranked_subquery.c.row_num == 1)
            .order_by(
                latest_availability.target_date.asc(),
                latest_availability.slot_time.asc().nulls_last(),
                latest_availability.option_name.asc().nulls_last(),
                latest_availability.observed_at.desc(),
            )
        )
        rows = await self.session.scalars(rows_stmt)
        items = self._collapse_latest_rows(list(rows.all()), limit=limit)
        latest_observed_at = max((row.observed_at for row in items), default=None)
        return latest_observed_at, items

    @staticmethod
    def _collapse_latest_rows(rows: list[Price] | list[Availability], *, limit: int) -> list[Price] | list[Availability]:
        if not rows:
            return []

        latest_by_exact_key: dict[tuple[UUID, date, int, str | None, str | None, object], Price | Availability] = {}
        for row in rows:
            exact_key = (
                row.ota_source_id,
                row.target_date,
                row.horizon_days,
                row.option_name,
                row.language_code,
                row.slot_time,
            )
            existing = latest_by_exact_key.get(exact_key)
            if existing is None or row.observed_at > existing.observed_at:
                latest_by_exact_key[exact_key] = row

        grouped_by_option: dict[tuple[UUID, date, int, str | None, str | None], list[Price | Availability]] = defaultdict(list)
        for row in latest_by_exact_key.values():
            option_key = (
                row.ota_source_id,
                row.target_date,
                row.horizon_days,
                row.option_name,
                row.language_code,
            )
            grouped_by_option[option_key].append(row)

        collapsed: list[Price | Availability] = []
        for option_rows in grouped_by_option.values():
            with_slot = [row for row in option_rows if row.slot_time is not None]
            if with_slot:
                collapsed.extend(with_slot)
                continue

            latest_row = max(option_rows, key=lambda item: item.observed_at)
            collapsed.append(latest_row)

        collapsed.sort(
            key=lambda item: (
                item.target_date,
                item.slot_time is None,
                item.slot_time or datetime.min.time(),
                item.option_name or "",
                item.observed_at,
            )
        )

        return collapsed[:limit]

    async def price_timeseries(
        self,
        *,
        tour_code: str,
        horizon_days: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 50_000,
    ) -> list[Price]:
        """Histórico de precios con deduplicación por fila lógica (última observación gana).

        Antes se hacía ``order_by(...).limit(N)`` sobre filas crudas: con muchas filas GYG
        las últimas 5000 eran casi todas GetYourGuide y **desaparecía Viator** en la tendencia.
        """
        filters: list = [Tour.internal_code == tour_code]
        if horizon_days is not None:
            filters.append(Price.horizon_days == horizon_days)

        if from_date is not None and to_date is not None:
            filters.append(
                or_(
                    and_(Price.target_date >= from_date, Price.target_date <= to_date),
                    and_(
                        func.date(Price.observed_at) >= from_date,
                        func.date(Price.observed_at) <= to_date,
                    ),
                )
            )
        else:
            if from_date is not None:
                filters.append(Price.target_date >= from_date)
            if to_date is not None:
                filters.append(Price.target_date <= to_date)

        ranked_rows = (
            select(
                Price,
                func.row_number()
                .over(
                    partition_by=(
                        Price.ota_source_id,
                        Price.target_date,
                        Price.horizon_days,
                        Price.option_name,
                        Price.language_code,
                        Price.slot_time,
                    ),
                    order_by=Price.observed_at.desc(),
                )
                .label("row_num"),
            )
            .join(OtaSource, OtaSource.id == Price.ota_source_id)
            .join(Tour, Tour.id == OtaSource.tour_id)
            .where(*filters)
        ).subquery()

        price_alias = aliased(Price, ranked_rows)
        rows_stmt = (
            select(price_alias)
            .where(ranked_rows.c.row_num == 1)
            .order_by(price_alias.observed_at.asc(), price_alias.target_date.asc())
            .limit(min(limit, 500_000))
        )
        rows = await self.session.scalars(rows_stmt)
        return list(rows.all())

    async def source_name_by_id(self, source_id: UUID) -> str | None:
        stmt = select(OtaSource.ota_name).where(OtaSource.id == source_id)
        return await self.session.scalar(stmt)

    async def source_names_by_ids(self, source_ids: set[UUID]) -> dict[UUID, str]:
        if not source_ids:
            return {}
        stmt = select(OtaSource.id, OtaSource.ota_name).where(OtaSource.id.in_(source_ids))
        rows = await self.session.execute(stmt)
        return {source_id: ota_name for source_id, ota_name in rows.all()}
