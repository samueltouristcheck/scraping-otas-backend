"""initial_schema

Revision ID: 20260302_0001
Revises:
Create Date: 2026-03-02 12:30:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260302_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tours",
        sa.Column("attraction", sa.String(length=100), nullable=False),
        sa.Column("variant", sa.String(length=100), nullable=False),
        sa.Column("internal_code", sa.String(length=120), nullable=False),
        sa.Column("market", sa.String(length=10), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tours")),
        sa.UniqueConstraint("internal_code", name=op.f("uq_tours_internal_code")),
    )
    op.create_index(op.f("ix_tours_attraction"), "tours", ["attraction"], unique=False)
    op.create_index("ix_tours_attraction_variant", "tours", ["attraction", "variant"], unique=False)

    op.create_table(
        "ota_sources",
        sa.Column("tour_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ota_name", sa.String(length=30), nullable=False),
        sa.Column("external_product_id", sa.String(length=200), nullable=False),
        sa.Column("product_url", sa.Text(), nullable=False),
        sa.Column("default_currency", sa.String(length=3), nullable=False),
        sa.Column("default_locale", sa.String(length=10), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tour_id"], ["tours.id"], name=op.f("fk_ota_sources_tour_id_tours"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ota_sources")),
        sa.UniqueConstraint("ota_name", "external_product_id", name="uq_ota_sources_ota_product"),
    )
    op.create_index(op.f("ix_ota_sources_ota_name"), "ota_sources", ["ota_name"], unique=False)
    op.create_index("ix_ota_sources_tour_ota", "ota_sources", ["tour_id", "ota_name"], unique=False)

    op.create_table(
        "prices",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ota_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scrape_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("horizon_days", sa.SmallInteger(), nullable=False),
        sa.Column("slot_time", sa.Time(), nullable=True),
        sa.Column("language_code", sa.String(length=10), nullable=True),
        sa.Column("option_name", sa.String(length=120), nullable=True),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("list_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("final_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("horizon_days IN (0, 7, 30, 90, 180)", name="horizon_days_allowed"),
        sa.ForeignKeyConstraint(["ota_source_id"], ["ota_sources.id"], name=op.f("fk_prices_ota_source_id_ota_sources"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prices")),
        sa.UniqueConstraint(
            "ota_source_id",
            "scrape_run_id",
            "target_date",
            "slot_time",
            "language_code",
            "option_name",
            name="uq_prices_snapshot_row",
        ),
    )
    op.create_index(op.f("ix_prices_observed_at"), "prices", ["observed_at"], unique=False)
    op.create_index(op.f("ix_prices_slot_time"), "prices", ["slot_time"], unique=False)
    op.create_index(op.f("ix_prices_target_date"), "prices", ["target_date"], unique=False)
    op.create_index("ix_prices_source_target_observed", "prices", ["ota_source_id", "target_date", "observed_at"], unique=False)

    op.create_table(
        "availability",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ota_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scrape_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("horizon_days", sa.SmallInteger(), nullable=False),
        sa.Column("slot_time", sa.Time(), nullable=True),
        sa.Column("language_code", sa.String(length=10), nullable=True),
        sa.Column("option_name", sa.String(length=120), nullable=True),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.Column("seats_available", sa.Integer(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("horizon_days IN (0, 7, 30, 90, 180)", name="horizon_days_allowed"),
        sa.ForeignKeyConstraint(["ota_source_id"], ["ota_sources.id"], name=op.f("fk_availability_ota_source_id_ota_sources"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_availability")),
        sa.UniqueConstraint(
            "ota_source_id",
            "scrape_run_id",
            "target_date",
            "slot_time",
            "language_code",
            "option_name",
            name="uq_availability_snapshot_row",
        ),
    )
    op.create_index(op.f("ix_availability_observed_at"), "availability", ["observed_at"], unique=False)
    op.create_index(op.f("ix_availability_slot_time"), "availability", ["slot_time"], unique=False)
    op.create_index(op.f("ix_availability_target_date"), "availability", ["target_date"], unique=False)
    op.create_index(
        "ix_availability_source_target_observed",
        "availability",
        ["ota_source_id", "target_date", "observed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_availability_source_target_observed", table_name="availability")
    op.drop_index(op.f("ix_availability_target_date"), table_name="availability")
    op.drop_index(op.f("ix_availability_slot_time"), table_name="availability")
    op.drop_index(op.f("ix_availability_observed_at"), table_name="availability")
    op.drop_table("availability")

    op.drop_index("ix_prices_source_target_observed", table_name="prices")
    op.drop_index(op.f("ix_prices_target_date"), table_name="prices")
    op.drop_index(op.f("ix_prices_slot_time"), table_name="prices")
    op.drop_index(op.f("ix_prices_observed_at"), table_name="prices")
    op.drop_table("prices")

    op.drop_index("ix_ota_sources_tour_ota", table_name="ota_sources")
    op.drop_index(op.f("ix_ota_sources_ota_name"), table_name="ota_sources")
    op.drop_table("ota_sources")

    op.drop_index("ix_tours_attraction_variant", table_name="tours")
    op.drop_index(op.f("ix_tours_attraction"), table_name="tours")
    op.drop_table("tours")
