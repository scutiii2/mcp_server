import secrets as secrets_module

from flask import Flask
from flask_login import LoginManager
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from src.models import Account, LoginAttempt, Permission, Role, db
from src.services import otp_service
from src.services.authz import registered_permissions
from src.utils.config_loader import load_env_secrets

login_manager = LoginManager()
login_manager.login_view = "auth.login"


def init_login_manager(app: Flask) -> None:
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Account, int(user_id))


def verify_credentials(db_session, username: str, password: str) -> Account | None:
    account = db_session.query(Account).filter_by(username=username).first()
    if account is None or not account.is_active:
        return None
    if not check_password_hash(account.password_hash, password):
        return None
    return account


def record_login_attempt(
    db_session, ip_address: str, account_id: int | None, success: bool
) -> LoginAttempt:
    attempt = LoginAttempt(ip_address=ip_address, account_id=account_id, success=success)
    db_session.add(attempt)
    db_session.commit()
    return attempt


class RegistrationError(ValueError):
    """Registration rejected for a reason safe to show the registrant."""


def _duplicate_account_message(db_session, username: str, email: str) -> str | None:
    if db_session.query(Account.id).filter_by(username=username).first() is not None:
        return "Username is already taken"
    if db_session.query(Account.id).filter_by(email=email).first() is not None:
        return "Email is already registered"
    return None


def register_account(
    db_session, username: str, email: str, password: str, invite_code: str
) -> Account | None:
    """Returns None for a bad invite; raises RegistrationError for a duplicate username/email.

    The invite is checked first so account existence is only revealed to invite holders,
    and it is left unconsumed when registration is rejected.
    """
    invite = otp_service.find_valid_invite(db_session, invite_code)
    if invite is None:
        return None

    duplicate = _duplicate_account_message(db_session, username, email)
    if duplicate is not None:
        raise RegistrationError(duplicate)

    account = Account(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
    )
    db_session.add(account)
    try:
        otp_service.consume_invite(db_session, invite)
    except IntegrityError as error:
        # Lost a race with a concurrent registration; rollback also restores the invite.
        db_session.rollback()
        raise RegistrationError(
            _duplicate_account_message(db_session, username, email)
            or "Username or email is already registered"
        ) from error
    return account


def _sync_administrator_role_permissions(db_session, role: Role) -> None:
    existing_names = {p.name for p in role.permissions}
    for name in registered_permissions():
        if name in existing_names:
            continue
        permission = db_session.query(Permission).filter_by(name=name).first()
        if permission is None:
            permission = Permission(name=name)
            db_session.add(permission)
        role.permissions.append(permission)
    db_session.commit()


def _sync_bootstrap_admin(db_session, admin: Account, username, email, password) -> None:
    taken = {
        row.username: row.email
        for row in db_session.query(Account).filter(Account.id != admin.id)
    }
    if username not in taken:
        admin.username = username
    if email not in taken.values():
        admin.email = email
    # No configured password: leave the existing hash alone rather than rotating it.
    if password and not check_password_hash(admin.password_hash, password):
        admin.password_hash = generate_password_hash(password)
    db_session.commit()


def ensure_bootstrap_admin(db_session, secrets_dir) -> None:
    role = db_session.query(Role).filter_by(name="Administrator").first()
    if role is None:
        role = Role(name="Administrator", description="Full-access bootstrap role")
        db_session.add(role)
        db_session.commit()

    _sync_administrator_role_permissions(db_session, role)

    bootstrap_secrets = load_env_secrets(secrets_dir / "secret_bootstrap_admin.env")
    username = bootstrap_secrets.get("BOOTSTRAP_ADMIN_USERNAME") or "admin"
    email = bootstrap_secrets.get("BOOTSTRAP_ADMIN_EMAIL") or "admin@example.com"
    password = bootstrap_secrets.get("BOOTSTRAP_ADMIN_PASSWORD")

    existing = db_session.query(Account).filter_by(is_protected=True).first()
    if existing is not None:
        _sync_bootstrap_admin(db_session, existing, username, email, password)
        return

    if db_session.query(Account).count() > 0:
        return

    generated = False
    if not password:
        password = secrets_module.token_urlsafe(16)
        generated = True

    admin = Account(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        is_protected=True,
    )
    admin.roles.append(role)
    db_session.add(admin)
    db_session.commit()

    if generated:
        print(
            f"Bootstrap admin created: username={username} password={password} "
            "(save this now, it will not be shown again)"
        )


def update_account_profile(
    db_session,
    account: Account,
    current_password: str,
    new_email: str | None,
    new_password: str | None,
) -> bool:
    if not check_password_hash(account.password_hash, current_password):
        return False
    if new_email:
        account.email = new_email
    if new_password:
        account.password_hash = generate_password_hash(new_password)
    db_session.commit()
    return True
