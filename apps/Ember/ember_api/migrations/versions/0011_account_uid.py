"""accounts.uid: a stable id that never changes or repeats.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("uid", sa.String(32), nullable=True))
    conn = op.get_bind()
    for (account_id,) in conn.execute(sa.text("SELECT id FROM accounts")).fetchall():
        conn.execute(sa.text("UPDATE accounts SET uid = :uid WHERE id = :id"), {"uid": uuid.uuid4().hex, "id": account_id})
    with op.batch_alter_table("accounts") as batch:
        batch.alter_column("uid", existing_type=sa.String(32), nullable=False)
        batch.create_index("ix_accounts_uid", ["uid"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.drop_index("ix_accounts_uid")
        batch.drop_column("uid")
