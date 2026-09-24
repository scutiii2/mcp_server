from pathlib import Path

from flask import Blueprint, flash, redirect, render_template, request, url_for
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
    if current_user.is_authenticated:
        return redirect("/")
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
    if current_user.is_authenticated:
        return redirect("/")
    if request.method == "GET":
        return render_template("register.html", error=None)

    username = request.form.get("username", "")
    email = request.form.get("email", "")
    password = request.form.get("password", "")
    invite_code = request.form.get("invite_code", "")

    try:
        account = auth_service.register_account(db.session, username, email, password, invite_code)
    except auth_service.RegistrationError as error:
        return render_template("register.html", error=str(error)), 409
    if account is None:
        return render_template("register.html", error="Invalid or expired invite code"), 400

    log_service.log_action(db.session, account, "auth.register", "Account registered")

    # Account is already committed, so log in even if the email fails;
    # the verify page's "Resend code" lets the user retry once SMTP works.
    login_user(account)
    verification, code = otp_service.create_email_verification(db.session, account)
    try:
        email_service.send_email_verification(account.email, code, verification.expires_at)
    except email_service.EmailDeliveryError as error:
        flash(str(error))
    return redirect(url_for("auth.verify_email"))


def _unverified_account_or_redirect():
    """Verification pages need a logged-in account that is not yet verified."""
    if not current_user.is_authenticated:
        return None, redirect(url_for("auth.login"))
    if current_user.email_verified:
        return None, redirect("/")
    return current_user, None


@blueprint.route("/verify-email", methods=["GET", "POST"])
def verify_email():
    account, blocked = _unverified_account_or_redirect()
    if blocked is not None:
        return blocked

    if request.method == "GET":
        return render_template("verify_email.html", email=account.email, error=None)

    code = request.form.get("code", "")
    verification = otp_service.find_valid_email_verification(db.session, account, code)
    if verification is None:
        return render_template("verify_email.html", email=account.email, error="Invalid or expired code"), 400

    otp_service.consume_email_verification(db.session, verification)
    log_service.log_action(db.session, account, "auth.verify_email", "Email verified")
    flash("Email verified")
    return redirect("/")


@blueprint.route("/verify-email/resend", methods=["POST"])
def resend_verification_email():
    account, blocked = _unverified_account_or_redirect()
    if blocked is not None:
        return blocked

    verification, code = otp_service.create_email_verification(db.session, account)
    try:
        email_service.send_email_verification(account.email, code, verification.expires_at)
    except email_service.EmailDeliveryError as error:
        return render_template("verify_email.html", email=account.email, error=str(error)), 503
    return render_template("verify_email.html", email=account.email, error=None, resent=True)


@blueprint.route("/logout")
def logout():
    if current_user.is_authenticated:
        log_service.log_action(db.session, current_user, "auth.logout", "Logged out")
    logout_user()
    return redirect(url_for("auth.login"))
