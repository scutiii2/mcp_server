"""Private extensions: MCP servers an account added for itself (user_extensions).

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_extensions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(40), nullable=False),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("headers_encrypted", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("account_id", "slug"),
    )
    op.create_index("ix_user_extensions_account_id", "user_extensions", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_user_extensions_account_id", table_name="user_extensions")
    op.drop_table("user_extensions")
