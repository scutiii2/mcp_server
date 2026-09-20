import pytest

from src.models import Account, Permission, Role, db
from src.services import admin_service
from src.services.authz import require_permission


def test_create_role_persists(app):
    with app.app_context():
        role = admin_service.create_role(db.session, "editor", "Can edit content")

        assert role.id is not None
        fetched = db.session.query(Role).filter_by(name="editor").one()
        assert fetched.description == "Can edit content"


def test_list_roles_returns_all_roles_sorted_by_name(app):
    with app.app_context():
        db.session.add(Role(name="zeta"))
        db.session.add(Role(name="alpha"))
        db.session.commit()

        roles = admin_service.list_roles(db.session)

        assert [r.name for r in roles] == ["alpha", "zeta"]


def test_list_accounts_returns_all_accounts_sorted_by_username(app):
    with app.app_context():
        db.session.add(Account(username="zed", email="zed@example.com", password_hash="hashed"))
        db.session.add(Account(username="amy", email="amy@example.com", password_hash="hashed"))
        db.session.commit()

        accounts = admin_service.list_accounts(db.session)

        assert [a.username for a in accounts] == ["amy", "zed"]


def test_assign_permission_to_role_creates_permission_if_missing(app):
    @require_permission("admin_test.grant_action")
    def _dummy_view():
        return "ok"

    with app.app_context():
        role = Role(name="grantee")
        db.session.add(role)
        db.session.commit()

        permission = admin_service.assign_permission_to_role(db.session, role, "admin_test.grant_action")

        assert permission.name == "admin_test.grant_action"
        fetched_role = db.session.query(Role).filter_by(name="grantee").one()
        assert [p.name for p in fetched_role.permissions] == ["admin_test.grant_action"]


def test_assign_permission_to_role_is_idempotent(app):
    @require_permission("admin_test.idempotent_action")
    def _dummy_view():
        return "ok"

    with app.app_context():
        role = Role(name="idempotent_role")
        db.session.add(role)
        db.session.commit()

        admin_service.assign_permission_to_role(db.session, role, "admin_test.idempotent_action")
        admin_service.assign_permission_to_role(db.session, role, "admin_test.idempotent_action")

        fetched_role = db.session.query(Role).filter_by(name="idempotent_role").one()
        assert len(fetched_role.permissions) == 1


def test_assign_permission_to_role_rejects_unregistered_permission(app):
    with app.app_context():
        role = Role(name="strict_role")
        db.session.add(role)
        db.session.commit()

        with pytest.raises(ValueError):
            admin_service.assign_permission_to_role(db.session, role, "totally.made_up_permission")


def test_remove_permission_from_role(app):
    with app.app_context():
        role = Role(name="revokee")
        permission = Permission(name="revoke_test.action")
        role.permissions.append(permission)
        db.session.add(role)
        db.session.commit()

        admin_service.remove_permission_from_role(db.session, role, "revoke_test.action")

        fetched_role = db.session.query(Role).filter_by(name="revokee").one()
        assert fetched_role.permissions == []


def test_assign_role_to_account(app):
    with app.app_context():
        account = Account(username="member", email="member@example.com", password_hash="hashed")
        role = Role(name="member_role")
        db.session.add_all([account, role])
        db.session.commit()

        admin_service.assign_role_to_account(db.session, account, role)

        fetched_account = db.session.query(Account).filter_by(username="member").one()
        assert [r.name for r in fetched_account.roles] == ["member_role"]


def test_remove_role_from_account(app):
    with app.app_context():
        account = Account(username="leaving", email="leaving@example.com", password_hash="hashed")
        role = Role(name="leaving_role")
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()

        admin_service.remove_role_from_account(db.session, account, role)

        fetched_account = db.session.query(Account).filter_by(username="leaving").one()
        assert fetched_account.roles == []


def test_remove_role_from_account_raises_for_protected_account(app):
    with app.app_context():
        account = Account(
            username="untouchable",
            email="untouchable@example.com",
            password_hash="hashed",
            is_protected=True,
        )
        role = Role(name="untouchable_role")
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()

        with pytest.raises(admin_service.ProtectedAccountError):
            admin_service.remove_role_from_account(db.session, account, role)

        fetched_account = db.session.query(Account).filter_by(username="untouchable").one()
        assert [r.name for r in fetched_account.roles] == ["untouchable_role"]


def test_update_role_changes_name_and_description(app):
    with app.app_context():
        role = Role(name="old_name", description="old description")
        db.session.add(role)
        db.session.commit()
        role_id = role.id

        admin_service.update_role(db.session, role, "new_name", "new description")

        fetched = db.session.get(Role, role_id)
        assert fetched.name == "new_name"
        assert fetched.description == "new description"


def test_update_role_rejects_duplicate_name(app):
    with app.app_context():
        db.session.add(Role(name="taken_name"))
        role = Role(name="renaming_role")
        db.session.add(role)
        db.session.commit()

        with pytest.raises(ValueError):
            admin_service.update_role(db.session, role, "taken_name", None)


def test_update_role_allows_keeping_its_own_name(app):
    with app.app_context():
        role = Role(name="same_name", description="old")
        db.session.add(role)
        db.session.commit()

        admin_service.update_role(db.session, role, "same_name", "new description")

        fetched = db.session.query(Role).filter_by(name="same_name").one()
        assert fetched.description == "new description"


def test_update_role_rejects_renaming_administrator_role(app):
    with app.app_context():
        role = Role(name="Administrator", description="Full-access bootstrap role")
        db.session.add(role)
        db.session.commit()

        with pytest.raises(admin_service.ProtectedRoleError):
            admin_service.update_role(db.session, role, "NotAdministrator", "desc")


def test_update_role_allows_editing_administrator_description(app):
    with app.app_context():
        role = Role(name="Administrator", description="old")
        db.session.add(role)
        db.session.commit()

        admin_service.update_role(db.session, role, "Administrator", "new description")

        fetched = db.session.query(Role).filter_by(name="Administrator").one()
        assert fetched.description == "new description"


def test_delete_role_removes_it(app):
    with app.app_context():
        role = Role(name="deletable_role")
        db.session.add(role)
        db.session.commit()
        role_id = role.id

        admin_service.delete_role(db.session, role)

        assert db.session.get(Role, role_id) is None


def test_delete_role_clears_account_and_permission_associations(app):
    with app.app_context():
        account = Account(username="deletee", email="deletee@example.com", password_hash="hashed")
        permission = Permission(name="deletable_role.perm")
        role = Role(name="deletable_linked_role")
        role.permissions.append(permission)
        account.roles.append(role)
        db.session.add_all([account, role])
        db.session.commit()
        account_id = account.id
        permission_id = permission.id

        admin_service.delete_role(db.session, role)

        fetched_account = db.session.get(Account, account_id)
        assert fetched_account.roles == []
        fetched_permission = db.session.get(Permission, permission_id)
        assert fetched_permission is not None
        assert fetched_permission.roles == []


def test_list_permissions_returns_all_permissions_sorted_by_name(app):
    with app.app_context():
        db.session.add(Permission(name="zeta.perm"))
        db.session.add(Permission(name="alpha.perm"))
        db.session.commit()

        permissions = admin_service.list_permissions(db.session)

        assert [p.name for p in permissions] == ["alpha.perm", "zeta.perm"]


def test_update_account_changes_username_and_email(app):
    with app.app_context():
        account = Account(username="old_name", email="old@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()
        account_id = account.id

        admin_service.update_account(db.session, account, "new_name", "new@example.com")

        fetched = db.session.get(Account, account_id)
        assert fetched.username == "new_name"
        assert fetched.email == "new@example.com"


def test_update_account_rejects_duplicate_username(app):
    with app.app_context():
        db.session.add(Account(username="taken", email="taken@example.com", password_hash="hashed"))
        account = Account(username="renaming", email="renaming@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()

        with pytest.raises(ValueError):
            admin_service.update_account(db.session, account, "taken", "renaming@example.com")


def test_update_account_rejects_duplicate_email(app):
    with app.app_context():
        db.session.add(Account(username="other", email="taken@example.com", password_hash="hashed"))
        account = Account(username="renaming2", email="renaming2@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()

        with pytest.raises(ValueError):
            admin_service.update_account(db.session, account, "renaming2", "taken@example.com")


def test_update_account_raises_for_protected_account(app):
    with app.app_context():
        account = Account(
            username="protected_edit",
            email="protected_edit@example.com",
            password_hash="hashed",
            is_protected=True,
        )
        db.session.add(account)
        db.session.commit()

        with pytest.raises(admin_service.ProtectedAccountError):
            admin_service.update_account(db.session, account, "renamed", "renamed@example.com")


def test_delete_account_removes_it(app):
    with app.app_context():
        actor = Account(username="actor", email="actor@example.com", password_hash="hashed")
        account = Account(username="deletable_account", email="deletable@example.com", password_hash="hashed")
        db.session.add_all([actor, account])
        db.session.commit()
        account_id = account.id

        admin_service.delete_account(db.session, account, actor)

        assert db.session.get(Account, account_id) is None


def test_delete_account_raises_for_protected_account(app):
    with app.app_context():
        actor = Account(username="actor2", email="actor2@example.com", password_hash="hashed")
        account = Account(
            username="protected_delete",
            email="protected_delete@example.com",
            password_hash="hashed",
            is_protected=True,
        )
        db.session.add_all([actor, account])
        db.session.commit()
        account_id = account.id

        with pytest.raises(admin_service.ProtectedAccountError):
            admin_service.delete_account(db.session, account, actor)

        assert db.session.get(Account, account_id) is not None


def test_delete_account_raises_for_self_delete(app):
    with app.app_context():
        account = Account(username="self_deleter", email="self_deleter@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()
        account_id = account.id

        with pytest.raises(admin_service.ProtectedAccountError):
            admin_service.delete_account(db.session, account, account)

        assert db.session.get(Account, account_id) is not None


def test_update_permission_changes_description(app):
    with app.app_context():
        permission = Permission(name="desc_test.action", description="old")
        db.session.add(permission)
        db.session.commit()
        permission_id = permission.id

        admin_service.update_permission(db.session, permission, "new description")

        fetched = db.session.get(Permission, permission_id)
        assert fetched.description == "new description"
        assert fetched.name == "desc_test.action"


def test_delete_permission_removes_it_and_role_association(app):
    with app.app_context():
        role = Role(name="perm_delete_role")
        permission = Permission(name="deletable_perm.action")
        role.permissions.append(permission)
        db.session.add(role)
        db.session.commit()
        permission_id = permission.id
        role_id = role.id

        admin_service.delete_permission(db.session, permission)

        assert db.session.get(Permission, permission_id) is None
        fetched_role = db.session.get(Role, role_id)
        assert fetched_role.permissions == []


def test_delete_role_rejects_deleting_administrator_role(app):
    with app.app_context():
        role = Role(name="Administrator", description="Full-access bootstrap role")
        db.session.add(role)
        db.session.commit()
        role_id = role.id

        with pytest.raises(admin_service.ProtectedRoleError):
            admin_service.delete_role(db.session, role)

        assert db.session.get(Role, role_id) is not None
