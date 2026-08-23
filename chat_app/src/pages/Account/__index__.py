from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from src.models import db
from src.services import auth_service, log_service
from src.services.authz import has_permission, register_permission, require_login

blueprint = Blueprint(
    "account", __name__, template_folder=".", static_folder=".", static_url_path="/static"
)

PAGE_PERMISSION = None
PAGE_DESCRIPTION = "View and edit your username, email, and password."

register_permission("account.edit")


@blueprint.route("/", methods=["GET", "POST"])
@require_login()
def profile():
    can_edit = has_permission(current_user, "account.edit")

    if request.method == "POST":
        if not can_edit:
            flash("You don't have permission to edit your profile")
            return redirect(url_for("account.profile"))

        current_password = request.form.get("current_password", "")
        new_email = request.form.get("email", "").strip() or None
        new_password = request.form.get("new_password", "").strip() or None

        success = auth_service.update_account_profile(
            db.session, current_user, current_password, new_email, new_password
        )
        if success:
            log_service.log_action(db.session, current_user, "account.profile_update", "Profile updated")
            flash("Profile updated")
        else:
            flash("Current password is incorrect")
        return redirect(url_for("account.profile"))

    return render_template("account.html", can_edit=can_edit)
