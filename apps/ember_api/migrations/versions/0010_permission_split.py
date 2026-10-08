"""Split broad permissions once, preserving existing role access.

Legacy rows and associations are retained for rollback, but are no longer
recognized by the application. Re-running startup never restores revoked grants.
"""

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# Frozen migration data: never import the application's evolving registry.
SPLITS = {
    "admin.manage": (
        "accounts.view", "accounts.manage", "accounts.delete", "roles.view",
        "roles.manage", "roles.assign", "invites.manage", "settings.manage",
        "capabilities.manage", "usage.all.view",
    ),
    "tools.use": ("tools.view", "tools.execute", "files.upload", "files.download"),
    # Chat already allowed agent tool calls and attachment uploads.
    "chat.use": ("chat.share", "extensions.personal.manage", "tools.execute", "files.upload"),
}


def upgrade():
    conn = op.get_bind()
    for source, targets in SPLITS.items():
        for target in targets:
            conn.execute(sa.text(
                "INSERT INTO permissions (name, description) SELECT :name, NULL "
                "WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE name = :name)"
            ), {"name": target})
            conn.execute(sa.text(
                "INSERT INTO role_permission (role_id, permission_id) "
                "SELECT old.role_id, new.id FROM role_permission old "
                "JOIN permissions legacy ON legacy.id = old.permission_id "
                "JOIN permissions new ON new.name = :target "
                "WHERE legacy.name = :source AND NOT EXISTS "
                "(SELECT 1 FROM role_permission present WHERE present.role_id = old.role_id "
                "AND present.permission_id = new.id)"
            ), {"source": source, "target": target})


def downgrade():
    # Original broad grants are still present. Restore the pre-upgrade backup
    # instead if permission edits made after upgrade must also be undone.
    conn = op.get_bind()
    for name in sorted({name for targets in SPLITS.values() for name in targets}):
        conn.execute(sa.text(
            "DELETE FROM role_permission WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE name = :name)"
        ), {"name": name})
        conn.execute(sa.text("DELETE FROM permissions WHERE name = :name"), {"name": name})
