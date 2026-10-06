"""Which agent, provider and gateway spent usage tokens, and when (usage_records).

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("usage_records") as batch:
        batch.add_column(sa.Column("agent_id", sa.String(120), nullable=True))
        batch.add_column(sa.Column("provider_id", sa.String(60), nullable=True))
        batch.add_column(sa.Column("gateway", sa.String(60), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("finished_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("delegated_by", sa.String(120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("usage_records") as batch:
        batch.drop_column("delegated_by")
        batch.drop_column("finished_at")
        batch.drop_column("started_at")
        batch.drop_column("gateway")
        batch.drop_column("provider_id")
        batch.drop_column("agent_id")
