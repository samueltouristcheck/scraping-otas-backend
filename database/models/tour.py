from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base.base import Base
from database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Tour(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tours"

    attraction: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    variant: Mapped[str] = mapped_column(String(100), nullable=False)
    internal_code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    market: Mapped[str] = mapped_column(String(10), nullable=False, default="ES")
    city: Mapped[str] = mapped_column(String(100), nullable=False, default="Barcelona")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    ota_sources = relationship("OtaSource", back_populates="tour", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_tours_attraction_variant", "attraction", "variant"),
    )
