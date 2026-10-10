"""Give every role that can chat the new ticket-reporting permission, once.

Later revocations stick: re-running startup never restores a revoked grant.
`tickets.manage` is deliberately not granted to anyone here; the Administrator
role receives it at startup like every permission in the registry.
"""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

# Frozen migration data: never import the application's evolving registry.
SOURCE = "chat.use"
TARGET = "tickets.create"


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "INSERT INTO permissions (name, description) SELECT :name, NULL "
        "WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE name = :name)"
    ), {"name": TARGET})
    conn.execute(sa.text(
        "INSERT INTO role_permission (role_id, permission_id) "
        "SELECT old.role_id, new.id FROM role_permission old "
        "JOIN permissions legacy ON legacy.id = old.permission_id "
        "JOIN permissions new ON new.name = :target "
        "WHERE legacy.name = :source AND NOT EXISTS "
        "(SELECT 1 FROM role_permission present WHERE present.role_id = old.role_id "
        "AND present.permission_id = new.id)"
    ), {"source": SOURCE, "target": TARGET})


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM role_permission WHERE permission_id IN (SELECT id FROM permissions WHERE name = :name)"
    ), {"name": TARGET})
    conn.execute(sa.text("DELETE FROM permissions WHERE name = :name"), {"name": TARGET})
