from __future__ import annotations

from chat_app.auth import permissions


def test_role_rank_orders_the_three_built_in_tiers():
    assert permissions.role_rank(permissions.DEFAULT_ROLE) < permissions.role_rank(permissions.ADMIN_ROLE)
    assert permissions.role_rank(permissions.ADMIN_ROLE) < permissions.role_rank(permissions.EXECUTIVE_ROLE)


def test_role_rank_treats_an_unknown_role_as_unranked():
    """Every custom role (created via the account manager's "Create role"
    tab) is a scope bundle, not a position in the hierarchy - same rank
    as member."""
    assert permissions.role_rank("some-custom-role") == permissions.role_rank(permissions.DEFAULT_ROLE)


def test_executive_endpoints_are_not_in_any_scope():
    """The whole reason EXECUTIVE_ENDPOINTS exists as a separate set: if
    a logs endpoint were in SCOPES, admin would inherit it automatically
    (its stored value is "*" - every current and future scope), defeating
    the entire point of a tier above admin."""
    all_scoped_endpoints = {
        endpoint for entry in permissions.SCOPES.values() for endpoint in entry["endpoints"]
    }
    assert not (permissions.EXECUTIVE_ENDPOINTS & all_scoped_endpoints)
