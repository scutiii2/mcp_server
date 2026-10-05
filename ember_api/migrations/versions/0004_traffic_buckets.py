"""Hourly traffic counters for the Analytics page's Traffic tab (traffic_buckets).

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "traffic_buckets",
        sa.Column("hour", sa.DateTime(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("band", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("total_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("hour", "kind", "name", "status", "band"),
    )


def downgrade() -> None:
    op.drop_table("traffic_buckets")
