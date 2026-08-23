from functools import wraps

from flask import abort
from flask_login import current_user

_REGISTERED_PERMISSIONS: set[str] = set()


def register_permission(name: str) -> None:
    _REGISTERED_PERMISSIONS.add(name)


def registered_permissions() -> set[str]:
    return set(_REGISTERED_PERMISSIONS)


def account_permissions(account) -> set[str]:
    permissions: set[str] = set()
    for role in account.roles:
        for permission in role.permissions:
            permissions.add(permission.name)
    return permissions


def has_permission(account, permission_name: str) -> bool:
    return permission_name in account_permissions(account)


def require_login():
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            return view_func(*args, **kwargs)

        return wrapped

    return decorator


def require_permission(permission_name: str):
    register_permission(permission_name)

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if not has_permission(current_user, permission_name):
                abort(403)
            return view_func(*args, **kwargs)

        return wrapped

    return decorator
