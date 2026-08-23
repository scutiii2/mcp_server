from src.models import Account, Permission, Role
from src.services.authz import registered_permissions


class ProtectedAccountError(Exception):
    pass


class ProtectedRoleError(Exception):
    pass


_PROTECTED_ROLE_NAME = "Administrator"


def list_roles(db_session) -> list[Role]:
    return db_session.query(Role).order_by(Role.name).all()


def list_accounts(db_session) -> list[Account]:
    return db_session.query(Account).order_by(Account.username).all()


def create_role(db_session, name: str, description: str | None) -> Role:
    role = Role(name=name, description=description)
    db_session.add(role)
    db_session.commit()
    return role


def update_role(db_session, role: Role, name: str, description: str | None) -> Role:
    if role.name == _PROTECTED_ROLE_NAME and name != _PROTECTED_ROLE_NAME:
        raise ProtectedRoleError(f"Role '{_PROTECTED_ROLE_NAME}' cannot be renamed")
    existing = db_session.query(Role).filter(Role.name == name, Role.id != role.id).first()
    if existing is not None:
        raise ValueError(f"Role name '{name}' is already in use")
    role.name = name
    role.description = description
    db_session.commit()
    return role


def delete_role(db_session, role: Role) -> None:
    if role.name == _PROTECTED_ROLE_NAME:
        raise ProtectedRoleError(f"Role '{_PROTECTED_ROLE_NAME}' cannot be deleted")
    db_session.delete(role)
    db_session.commit()


def assign_permission_to_role(db_session, role: Role, permission_name: str) -> Permission:
    if permission_name not in registered_permissions():
        raise ValueError(f"Unknown permission: {permission_name}")

    permission = db_session.query(Permission).filter_by(name=permission_name).first()
    if permission is None:
        permission = Permission(name=permission_name)
        db_session.add(permission)
    if permission not in role.permissions:
        role.permissions.append(permission)
    db_session.commit()
    return permission


def remove_permission_from_role(db_session, role: Role, permission_name: str) -> None:
    role.permissions = [p for p in role.permissions if p.name != permission_name]
    db_session.commit()


def assign_role_to_account(db_session, account: Account, role: Role) -> None:
    if role not in account.roles:
        account.roles.append(role)
    db_session.commit()


def remove_role_from_account(db_session, account: Account, role: Role) -> None:
    if account.is_protected:
        raise ProtectedAccountError(
            f"Account '{account.username}' is protected; its roles cannot be stripped"
        )
    account.roles = [r for r in account.roles if r.id != role.id]
    db_session.commit()
