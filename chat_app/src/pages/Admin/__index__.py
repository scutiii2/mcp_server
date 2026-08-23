from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from src.models import Account, InviteOTP, Role, db
from src.services import admin_service, email_service, log_service, otp_service
from src.services.authz import registered_permissions, require_permission

blueprint = Blueprint(
    "admin",
    __name__,
    template_folder=".",
    static_folder=".",
    static_url_path="/static",
)

PAGE_PERMISSION = "admin.roles.manage"
PAGE_DESCRIPTION = "Manage roles, permissions, accounts, and invites."


_TABS = ("roles", "accounts", "invites")


@blueprint.route("/")
@require_permission("admin.roles.manage")
def dashboard():
    roles = admin_service.list_roles(db.session)
    accounts = admin_service.list_accounts(db.session)
    invites = db.session.query(InviteOTP).order_by(InviteOTP.created_at.desc()).limit(20).all()
    active_tab = request.args.get("tab", "roles")
    if active_tab not in _TABS:
        active_tab = "roles"
    return render_template(
        "view.html",
        roles=roles,
        accounts=accounts,
        invites=invites,
        available_permissions=sorted(registered_permissions()),
        active_tab=active_tab,
    )


@blueprint.route("/roles", methods=["POST"])
@require_permission("admin.roles.manage")
def create_role():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip() or None
    if not name:
        flash("Role name is required")
    else:
        admin_service.create_role(db.session, name, description)
        log_service.log_action(db.session, current_user, "admin.create_role", f"Created role '{name}'")
        flash(f"Role '{name}' created")
    return redirect(url_for("admin.dashboard", tab="roles"))


@blueprint.route("/roles/<int:role_id>/edit", methods=["POST"])
@require_permission("admin.roles.manage")
def update_role(role_id):
    role = db.session.get(Role, role_id)
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip() or None
    if role is None:
        flash("Role not found")
    elif not name:
        flash("Role name is required")
    else:
        try:
            admin_service.update_role(db.session, role, name, description)
            log_service.log_action(db.session, current_user, "admin.update_role", f"Updated role '{name}'")
            flash(f"Role '{name}' updated")
        except (ValueError, admin_service.ProtectedRoleError) as error:
            flash(str(error))
    return redirect(url_for("admin.dashboard", tab="roles"))


@blueprint.route("/roles/<int:role_id>/delete", methods=["POST"])
@require_permission("admin.roles.manage")
def delete_role(role_id):
    role = db.session.get(Role, role_id)
    if role is None:
        flash("Role not found")
    else:
        try:
            role_name = role.name
            admin_service.delete_role(db.session, role)
            log_service.log_action(db.session, current_user, "admin.delete_role", f"Deleted role '{role_name}'")
            flash(f"Role '{role_name}' deleted")
        except admin_service.ProtectedRoleError as error:
            flash(str(error))
    return redirect(url_for("admin.dashboard", tab="roles"))


@blueprint.route("/roles/<int:role_id>/permissions", methods=["POST"])
@require_permission("admin.roles.manage")
def assign_permission(role_id):
    role = db.session.get(Role, role_id)
    permission_name = request.form.get("permission_name", "")
    if role is None:
        flash("Role not found")
    else:
        try:
            admin_service.assign_permission_to_role(db.session, role, permission_name)
            log_service.log_action(
                db.session,
                current_user,
                "admin.assign_permission",
                f"Granted '{permission_name}' to role '{role.name}'",
            )
            flash(f"Granted '{permission_name}' to role '{role.name}'")
        except ValueError as error:
            flash(str(error))
    return redirect(url_for("admin.dashboard", tab="roles"))


@blueprint.route("/roles/<int:role_id>/permissions/remove", methods=["POST"])
@require_permission("admin.roles.manage")
def remove_permission(role_id):
    role = db.session.get(Role, role_id)
    permission_name = request.form.get("permission_name", "")
    if role is None:
        flash("Role not found")
    else:
        admin_service.remove_permission_from_role(db.session, role, permission_name)
        log_service.log_action(
            db.session,
            current_user,
            "admin.remove_permission",
            f"Revoked '{permission_name}' from role '{role.name}'",
        )
        flash(f"Revoked '{permission_name}' from role '{role.name}'")
    return redirect(url_for("admin.dashboard", tab="roles"))


@blueprint.route("/accounts/<int:account_id>/roles", methods=["POST"])
@require_permission("admin.roles.manage")
def assign_role(account_id):
    account = db.session.get(Account, account_id)
    role_id = request.form.get("role_id", type=int)
    role = db.session.get(Role, role_id) if role_id else None
    if account is None or role is None:
        flash("Account or role not found")
    else:
        admin_service.assign_role_to_account(db.session, account, role)
        log_service.log_action(
            db.session,
            current_user,
            "admin.assign_role",
            f"Assigned role '{role.name}' to '{account.username}'",
        )
        flash(f"Assigned role '{role.name}' to '{account.username}'")
    return redirect(url_for("admin.dashboard", tab="accounts"))


@blueprint.route("/accounts/<int:account_id>/roles/remove", methods=["POST"])
@require_permission("admin.roles.manage")
def remove_role(account_id):
    account = db.session.get(Account, account_id)
    role_id = request.form.get("role_id", type=int)
    role = db.session.get(Role, role_id) if role_id else None
    if account is None or role is None:
        flash("Account or role not found")
    else:
        try:
            admin_service.remove_role_from_account(db.session, account, role)
            log_service.log_action(
                db.session,
                current_user,
                "admin.remove_role",
                f"Removed role '{role.name}' from '{account.username}'",
            )
            flash(f"Removed role '{role.name}' from '{account.username}'")
        except admin_service.ProtectedAccountError as error:
            flash(str(error))
    return redirect(url_for("admin.dashboard", tab="accounts"))


@blueprint.route("/invites", methods=["POST"])
@require_permission("auth.invite")
def create_invite():
    invitee_email = request.form.get("invitee_email", "").strip() or None
    delivery_method = request.form.get("delivery_method", "manual")

    invite, code = otp_service.create_invite(
        db.session, current_user.id, invitee_email, delivery_method
    )
    log_service.log_action(
        db.session, current_user, "admin.create_invite", f"Generated invite (delivery={delivery_method})"
    )

    if delivery_method == "email" and invitee_email:
        email_service.send_invite_email(invitee_email, code, invite.expires_at)
        flash(f"Invite emailed to {invitee_email}")
    else:
        flash(f"Invite code (copy and share manually — shown once): {code}", "persistent")

    return redirect(url_for("admin.dashboard", tab="invites"))


@blueprint.route("/invites/<int:invite_id>/remove", methods=["POST"])
@require_permission("auth.invite")
def remove_invite(invite_id):
    invite = db.session.get(InviteOTP, invite_id)
    if invite is None:
        flash("Invite not found")
    else:
        otp_service.delete_invite(db.session, invite)
        log_service.log_action(
            db.session,
            current_user,
            "admin.remove_invite",
            f"Removed invite ({invite.invitee_email or 'no email'})",
        )
        flash("Invite removed")
    return redirect(url_for("admin.dashboard", tab="invites"))
