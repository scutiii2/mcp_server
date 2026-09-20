from pathlib import Path

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user

from src.models import Account, SecurityEvent, db
from src.services import auth_service, email_service, log_service, otp_service
from src.services.security.fingerprint import compute_fingerprint, is_new_device, record_device
from src.utils.config_loader import load_json_config

blueprint = Blueprint(
    "auth",
    __name__,
    template_folder=".",
    static_folder=".",
    static_url_path="/static",
)

PAGE_PERMISSION = None

_FINGERPRINT_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "config_security_fingerprint.json"
)


@blueprint.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", error=None)

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    ip_address = request.remote_addr or "unknown"

    account = auth_service.verify_credentials(db.session, username, password)
    auth_service.record_login_attempt(
        db.session, ip_address, account.id if account else None, account is not None
    )

    if account is None:
        return render_template("login.html", error="Invalid username or password"), 401

    fingerprint_config = load_json_config(_FINGERPRINT_CONFIG_PATH)
    fingerprint_hash = compute_fingerprint(
        fingerprint_config,
        request.headers.get("User-Agent", ""),
        request.headers.get("Accept-Language", ""),
        ip_address,
    )
    if is_new_device(db.session, account.id, fingerprint_hash):
        db.session.add(
            SecurityEvent(
                account_id=account.id,
                event_type="new_device",
                ip_address=ip_address,
                details="First login from this device fingerprint",
            )
        )
        db.session.commit()
    record_device(db.session, account.id, fingerprint_hash)

    login_user(account)
    log_service.log_action(db.session, account, "auth.login", "Login succeeded")
    return redirect("/")


@blueprint.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html", error=None)

    username = request.form.get("username", "")
    email = request.form.get("email", "")
    password = request.form.get("password", "")
    invite_code = request.form.get("invite_code", "")

    account = auth_service.register_account(db.session, username, email, password, invite_code)
    if account is None:
        return render_template("register.html", error="Invalid or expired invite code"), 400

    log_service.log_action(db.session, account, "auth.register", "Account registered")

    verification, code = otp_service.create_email_verification(db.session, account)
    email_service.send_email_verification(account.email, code, verification.expires_at)
    session["pending_verification_account_id"] = account.id
    return redirect(url_for("auth.verify_email"))


def _pending_verification_account() -> Account | None:
    account_id = session.get("pending_verification_account_id")
    if account_id is None:
        return None
    return db.session.get(Account, account_id)


@blueprint.route("/verify-email", methods=["GET", "POST"])
def verify_email():
    account = _pending_verification_account()
    if account is None:
        return redirect(url_for("auth.login"))
    if account.email_verified:
        session.pop("pending_verification_account_id", None)
        return redirect(url_for("auth.login"))

    if request.method == "GET":
        return render_template("verify_email.html", email=account.email, error=None)

    code = request.form.get("code", "")
    verification = otp_service.find_valid_email_verification(db.session, account, code)
    if verification is None:
        return render_template("verify_email.html", email=account.email, error="Invalid or expired code"), 400

    otp_service.consume_email_verification(db.session, verification)
    log_service.log_action(db.session, account, "auth.verify_email", "Email verified")
    session.pop("pending_verification_account_id", None)
    flash("Email verified — you can now log in")
    return redirect(url_for("auth.login"))


@blueprint.route("/verify-email/resend", methods=["POST"])
def resend_verification_email():
    account = _pending_verification_account()
    if account is None or account.email_verified:
        return redirect(url_for("auth.login"))

    verification, code = otp_service.create_email_verification(db.session, account)
    email_service.send_email_verification(account.email, code, verification.expires_at)
    return render_template("verify_email.html", email=account.email, error=None, resent=True)


@blueprint.route("/logout")
def logout():
    if current_user.is_authenticated:
        log_service.log_action(db.session, current_user, "auth.logout", "Logged out")
    logout_user()
    return redirect(url_for("auth.login"))
