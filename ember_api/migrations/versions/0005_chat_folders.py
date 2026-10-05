"""Chat folders and pinned chats (chat_folders, chats.folder_id, chats.pinned).

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_folders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("account_id", "name"),
    )
    op.create_index("ix_chat_folders_account_id", "chat_folders", ["account_id"])
    with op.batch_alter_table("chats") as batch:
        batch.add_column(sa.Column("folder_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_foreign_key("fk_chats_folder_id", "chat_folders", ["folder_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_chats_folder_id", ["folder_id"])


def downgrade() -> None:
    with op.batch_alter_table("chats") as batch:
        batch.drop_index("ix_chats_folder_id")
        batch.drop_constraint("fk_chats_folder_id", type_="foreignkey")
        batch.drop_column("pinned")
        batch.drop_column("folder_id")
    op.drop_index("ix_chat_folders_account_id", table_name="chat_folders")
    op.drop_table("chat_folders")
