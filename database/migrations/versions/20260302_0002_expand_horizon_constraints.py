"""expand_horizon_constraints

Revision ID: 20260302_0002
Revises: 20260302_0001
Create Date: 2026-03-02 12:55:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260302_0002"
down_revision: str | None = "20260302_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("horizon_days_allowed", "prices", type_="check")
    op.create_check_constraint(
        "horizon_days_allowed",
        "prices",
        "horizon_days >= 0 AND horizon_days <= 180",
    )

    op.drop_constraint("horizon_days_allowed", "availability", type_="check")
    op.create_check_constraint(
        "horizon_days_allowed",
        "availability",
        "horizon_days >= 0 AND horizon_days <= 180",
    )


def downgrade() -> None:
    op.drop_constraint("horizon_days_allowed", "prices", type_="check")
    op.create_check_constraint(
        "horizon_days_allowed",
        "prices",
        "horizon_days IN (0, 7, 30, 90, 180)",
    )

    op.drop_constraint("horizon_days_allowed", "availability", type_="check")
    op.create_check_constraint(
        "horizon_days_allowed",
        "availability",
        "horizon_days IN (0, 7, 30, 90, 180)",
    )
