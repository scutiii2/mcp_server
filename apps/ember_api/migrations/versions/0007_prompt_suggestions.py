"""Per-account switch for the chat's next-prompt suggestion (accounts.prompt_suggestions).

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("prompt_suggestions", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("prompt_suggestions")
