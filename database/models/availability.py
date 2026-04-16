from datetime import date, time
from uuid import UUID as UUIDType
from uuid import uuid4

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base.base import Base
from database.models.mixins import ObservedAtMixin


class Availability(Base, ObservedAtMixin):
    __tablename__ = "availability"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ota_source_id: Mapped[UUIDType] = mapped_column(ForeignKey("ota_sources.id", ondelete="CASCADE"), nullable=False)
    scrape_run_id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid4)

    target_date: Mapped[date] = mapped_column(nullable=False, index=True)
    horizon_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    slot_time: Mapped[time | None] = mapped_column(nullable=True, index=True)

    language_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    option_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    is_available: Mapped[bool] = mapped_column(nullable=False)
    seats_available: Mapped[int | None] = mapped_column(Integer, nullable=True)

    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    ota_source = relationship("OtaSource", back_populates="availabilities")

    __table_args__ = (
        CheckConstraint("horizon_days >= 0 AND horizon_days <= 180", name="horizon_days_allowed"),
        UniqueConstraint(
            "ota_source_id",
            "scrape_run_id",
            "target_date",
            "slot_time",
            "language_code",
            "option_name",
            name="uq_availability_snapshot_row",
        ),
        Index("ix_availability_source_target_observed", "ota_source_id", "target_date", "observed_at"),
    )
