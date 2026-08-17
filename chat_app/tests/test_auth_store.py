"""Tests for the users/roles/invite_codes SQLite store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from chat_app.auth import permissions, store


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "users.db"


def _invite(db_path, created_by="admin", role=permissions.DEFAULT_ROLE, ttl_hours=None):
    return store.create_invite_code(db_path, created_by=created_by, role=role, ttl_hours=ttl_hours)


# --- seeded roles ----------------------------------------------------------


def test_admin_and_member_roles_are_seeded(db_path):
    roles = {role["name"]: role for role in store.list_roles(db_path)}

    assert roles["admin"]["scopes"] == set(permissions.SCOPES)
    assert roles["member"]["scopes"] == {"chat", "capabilities", "invites"}


def test_executive_role_is_seeded_with_every_scope(db_path):
    """Seeded the same way admin is - executive's actual distinction from
    admin (Logs page, ranked role changes) is enforced outside this table
    entirely, not by anything stored in this row."""
    roles = {role["name"]: role for role in store.list_roles(db_path)}

    assert roles["executive"]["scopes"] == set(permissions.SCOPES)


def test_admin_role_cannot_be_deleted(db_path):
    with pytest.raises(store.ProtectedRole):
        store.delete_role(db_path, "admin")


def test_executive_role_cannot_be_deleted(db_path):
    with pytest.raises(store.ProtectedRole):
        store.delete_role(db_path, "executive")


# --- users / invites ---------------------------------------------------


def test_unknown_user_does_not_verify(db_path):
    assert store.verify_user(db_path, "nobody", "whatever") is False


def test_register_user_with_valid_code_succeeds(db_path):
    code = _invite(db_path).code

    store.register_user(db_path, "alice", "hunter2pass", code)

    assert store.verify_user(db_path, "alice", "hunter2pass") is True
    assert store.get_user_role(db_path, "alice") == permissions.DEFAULT_ROLE


def test_registered_user_gets_the_invites_role(db_path):
    store.create_role(db_path, "reviewer", {"capabilities"}, created_by="admin")
    code = _invite(db_path, role="reviewer").code

    store.register_user(db_path, "alice", "hunter2pass", code)

    assert store.get_user_role(db_path, "alice") == "reviewer"


def test_wrong_password_does_not_verify(db_path):
    code = _invite(db_path).code
    store.register_user(db_path, "alice", "hunter2pass", code)

    assert store.verify_user(db_path, "alice", "wrong-password") is False


def test_invite_code_is_single_use(db_path):
    code = _invite(db_path).code
    store.register_user(db_path, "alice", "hunter2pass", code)

    with pytest.raises(store.InvalidInviteCode):
        store.register_user(db_path, "bob", "anotherpass1", code)


def test_unknown_invite_code_is_rejected(db_path):
    with pytest.raises(store.InvalidInviteCode):
        store.register_user(db_path, "alice", "hunter2pass", "not-a-real-code")


def test_expired_invite_code_is_rejected(db_path):
    issued = _invite(db_path, ttl_hours=1)
    # Directly age the row rather than sleeping in a test.
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE invite_codes SET expires_at = ? WHERE code_id != ''", (past,))
    conn.commit()
    conn.close()

    with pytest.raises(store.InvalidInviteCode):
        store.register_user(db_path, "alice", "hunter2pass", issued.code)


def test_duplicate_username_is_rejected_and_code_is_not_burned(db_path):
    """A taken username must not consume the invite code - otherwise the
    person who typed a valid code loses it to someone else's mistake."""
    code1 = _invite(db_path).code
    store.register_user(db_path, "alice", "hunter2pass", code1)

    code2 = _invite(db_path).code
    with pytest.raises(store.UsernameTaken):
        store.register_user(db_path, "alice", "different-pass", code2)

    # code2 must still be usable, since registration never completed.
    store.register_user(db_path, "carol", "yet-another-pass", code2)
    assert store.verify_user(db_path, "carol", "yet-another-pass") is True


def test_registered_user_created_by_tracks_the_inviter(db_path):
    code = _invite(db_path, created_by="root-admin").code
    store.register_user(db_path, "alice", "hunter2pass", code)

    assert store.list_users(db_path)[0]["created_by"] == "root-admin"


# --- direct user creation / deletion / role assignment ------------------


def test_create_user_direct(db_path):
    store.create_user_direct(db_path, "bob", "hunter2pass", "member", created_by="admin")

    assert store.verify_user(db_path, "bob", "hunter2pass") is True
    assert store.get_user_role(db_path, "bob") == "member"


def test_create_user_direct_with_unknown_role_fails(db_path):
    with pytest.raises(store.UnknownRole):
        store.create_user_direct(db_path, "bob", "hunter2pass", "not-a-role", created_by="admin")


def test_delete_user(db_path):
    store.create_user_direct(db_path, "bob", "hunter2pass", "member", created_by="admin")

    store.delete_user(db_path, "bob")

    assert store.verify_user(db_path, "bob", "hunter2pass") is False
    with pytest.raises(store.UnknownUser):
        store.delete_user(db_path, "bob")


def test_set_user_role(db_path):
    store.create_role(db_path, "reviewer", {"capabilities"}, created_by="admin")
    store.create_user_direct(db_path, "bob", "hunter2pass", "member", created_by="admin")

    store.set_user_role(db_path, "bob", "reviewer")

    assert store.get_user_role(db_path, "bob") == "reviewer"


def test_set_user_role_with_unknown_role_fails(db_path):
    store.create_user_direct(db_path, "bob", "hunter2pass", "member", created_by="admin")

    with pytest.raises(store.UnknownRole):
        store.set_user_role(db_path, "bob", "not-a-role")


# --- custom roles --------------------------------------------------------


def test_create_and_delete_role(db_path):
    store.create_role(db_path, "reviewer", {"capabilities"}, created_by="admin")

    roles = {role["name"]: role for role in store.list_roles(db_path)}
    assert roles["reviewer"]["scopes"] == {"capabilities"}

    store.delete_role(db_path, "reviewer")
    assert "reviewer" not in {role["name"] for role in store.list_roles(db_path)}


def test_create_role_with_invalid_scope_fails(db_path):
    with pytest.raises(store.InvalidScope):
        store.create_role(db_path, "reviewer", {"not-a-scope"}, created_by="admin")


def test_create_role_with_taken_name_fails(db_path):
    store.create_role(db_path, "reviewer", {"capabilities"}, created_by="admin")

    with pytest.raises(store.RoleTaken):
        store.create_role(db_path, "reviewer", {"chat"}, created_by="admin")


def test_delete_role_in_use_by_a_user_fails(db_path):
    store.create_role(db_path, "reviewer", {"capabilities"}, created_by="admin")
    store.create_user_direct(db_path, "bob", "hunter2pass", "reviewer", created_by="admin")

    with pytest.raises(store.RoleInUse):
        store.delete_role(db_path, "reviewer")


def test_delete_role_in_use_by_a_live_invite_fails(db_path):
    store.create_role(db_path, "reviewer", {"capabilities"}, created_by="admin")
    _invite(db_path, role="reviewer")

    with pytest.raises(store.RoleInUse):
        store.delete_role(db_path, "reviewer")


def test_delete_role_with_only_expired_invites_succeeds(db_path):
    store.create_role(db_path, "reviewer", {"capabilities"}, created_by="admin")
    issued = _invite(db_path, role="reviewer", ttl_hours=1)

    import sqlite3

    conn = sqlite3.connect(str(db_path))
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE invite_codes SET expires_at = ? WHERE code_id != ''", (past,))
    conn.commit()
    conn.close()

    store.delete_role(db_path, "reviewer")  # should not raise
    assert issued.code  # sanity: fixture actually minted something


# --- invite listing --------------------------------------------------------


def test_registering_a_user_deletes_the_invite_code(db_path):
    """Redeeming a code removes its row outright rather than marking it
    used - there's nothing left to show in the account manager's invite
    list once it can never be redeemed again either way."""
    issued = _invite(db_path, created_by="admin", role="member", ttl_hours=24)

    store.register_user(db_path, "alice", "hunter2pass", issued.code)

    assert store.list_invite_codes(db_path) == []
    # The fact that matters - who invited whom - survives on the user row.
    assert store.list_users(db_path)[0]["created_by"] == "admin"


def test_delete_invite_code_revokes_an_outstanding_code(db_path):
    issued = _invite(db_path)
    [invite] = store.list_invite_codes(db_path)

    store.delete_invite_code(db_path, invite["code_id"])

    assert store.list_invite_codes(db_path) == []
    with pytest.raises(store.InvalidInviteCode):
        store.register_user(db_path, "alice", "hunter2pass", issued.code)


def test_delete_invite_code_with_unknown_id_raises(db_path):
    with pytest.raises(store.UnknownInvite):
        store.delete_invite_code(db_path, "not-a-real-code-id")


# --- gate codes --------------------------------------------------------


def _gate_code(db_path, created_by="admin", ttl_hours=1):
    return store.create_gate_code(db_path, created_by=created_by, ttl_hours=ttl_hours)


def test_create_gate_code_is_valid_immediately(db_path):
    issued = _gate_code(db_path)

    assert store.gate_code_is_valid(db_path, issued.code) is True


def test_wrong_gate_code_is_not_valid(db_path):
    _gate_code(db_path)

    assert store.gate_code_is_valid(db_path, "not-the-code") is False


def test_gate_code_is_multi_use(db_path):
    """Unlike an invite code, a gate code stays valid across many uses for
    its whole window - there's no claim/race logic, since it isn't tied to
    any one account."""
    issued = _gate_code(db_path)

    assert store.gate_code_is_valid(db_path, issued.code) is True
    assert store.gate_code_is_valid(db_path, issued.code) is True


def test_expired_gate_code_is_not_valid(db_path):
    issued = _gate_code(db_path, ttl_hours=1)
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE gate_codes SET expires_at = ? WHERE code_id = ?", (past, issued.code_id))
    conn.commit()
    conn.close()

    assert store.gate_code_is_valid(db_path, issued.code) is False


def test_list_gate_codes_excludes_and_purges_expired_rows(db_path):
    issued = _gate_code(db_path, ttl_hours=1)
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE gate_codes SET expires_at = ? WHERE code_id = ?", (past, issued.code_id))
    conn.commit()
    conn.close()

    assert store.list_gate_codes(db_path) == []

    # Purged outright, not just filtered - a direct query confirms the
    # row itself is gone, mirroring how invite_codes has no lazy-GC
    # precedent to compare against but delete_role's expired-invite path
    # already relies on the same "expired rows don't linger forever" idea.
    conn = sqlite3.connect(str(db_path))
    remaining = conn.execute("SELECT 1 FROM gate_codes").fetchone()
    conn.close()
    assert remaining is None


def test_list_gate_codes_includes_active_rows(db_path):
    issued = _gate_code(db_path, created_by="root-admin")

    [row] = store.list_gate_codes(db_path)

    assert row["code_id"] == issued.code_id
    assert row["created_by"] == "root-admin"
    assert row["expires_at"] == issued.expires_at


def test_delete_gate_code_revokes_it_immediately(db_path):
    issued = _gate_code(db_path)

    store.delete_gate_code(db_path, issued.code_id)

    assert store.gate_code_is_valid(db_path, issued.code) is False
    assert store.list_gate_codes(db_path) == []


def test_delete_gate_code_with_unknown_id_raises(db_path):
    with pytest.raises(store.UnknownGateCode):
        store.delete_gate_code(db_path, "not-a-real-code-id")


def test_any_gate_code_valid_reports_true_only_while_unexpired(db_path):
    assert store.any_gate_code_valid(db_path) is False

    issued = _gate_code(db_path, ttl_hours=1)
    assert store.any_gate_code_valid(db_path) is True

    import sqlite3

    conn = sqlite3.connect(str(db_path))
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE gate_codes SET expires_at = ? WHERE code_id = ?", (past, issued.code_id))
    conn.commit()
    conn.close()
    assert store.any_gate_code_valid(db_path) is False
