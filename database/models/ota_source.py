from uuid import UUID as UUIDType

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base.base import Base
from database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class OtaSource(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ota_sources"

    tour_id: Mapped[UUIDType] = mapped_column(ForeignKey("tours.id", ondelete="CASCADE"), nullable=False)
    ota_name: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    external_product_id: Mapped[str] = mapped_column(String(200), nullable=False)
    product_url: Mapped[str] = mapped_column(Text, nullable=False)
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    default_locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    tour = relationship("Tour", back_populates="ota_sources")
    prices = relationship("Price", back_populates="ota_source", cascade="all, delete-orphan")
    availabilities = relationship("Availability", back_populates="ota_source", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("ota_name", "external_product_id", name="uq_ota_sources_ota_product"),
        Index("ix_ota_sources_tour_ota", "tour_id", "ota_name"),
    )
