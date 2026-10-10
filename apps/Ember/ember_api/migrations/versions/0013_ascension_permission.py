"""Rename the game's permission from emberlings.play to ascension.play.

The grants stay with their roles: the existing permission row is renamed in place.
If both rows exist (startup already added the new one), the old one is dropped
after its grants move to the new one.
"""

from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

# Frozen migration data: never import the application's evolving registry.
OLD = "emberlings.play"
NEW = "ascension.play"


def _rename(source: str, target: str) -> None:
    conn = op.get_bind()
    has_target = conn.execute(sa.text("SELECT 1 FROM permissions WHERE name = :name"), {"name": target}).first()
    if not has_target:
        conn.execute(sa.text("UPDATE permissions SET name = :target WHERE name = :source"), {"source": source, "target": target})
        return
    conn.execute(sa.text(
        "INSERT INTO role_permission (role_id, permission_id) "
        "SELECT old.role_id, new.id FROM role_permission old "
        "JOIN permissions legacy ON legacy.id = old.permission_id "
        "JOIN permissions new ON new.name = :target "
        "WHERE legacy.name = :source AND NOT EXISTS "
        "(SELECT 1 FROM role_permission present WHERE present.role_id = old.role_id "
        "AND present.permission_id = new.id)"
    ), {"source": source, "target": target})
    conn.execute(sa.text(
        "DELETE FROM role_permission WHERE permission_id IN (SELECT id FROM permissions WHERE name = :source)"
    ), {"source": source})
    conn.execute(sa.text("DELETE FROM permissions WHERE name = :source"), {"source": source})


def upgrade():
    _rename(OLD, NEW)


def downgrade():
    _rename(NEW, OLD)
