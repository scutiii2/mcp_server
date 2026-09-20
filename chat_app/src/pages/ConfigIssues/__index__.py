from flask import Blueprint, current_app, render_template

from src.services.authz import register_permission

blueprint = Blueprint("configissues", __name__, template_folder=".")

PAGE_PERMISSION = "config.issues.view"
PAGE_DESCRIPTION = "Lists configs/ and secrets/ values that are wrong, missing, or still placeholders."

register_permission("config.issues.view")


# Deliberately not login-gated: while a config is broken every other page
# redirects here, and a broken secret_app.env/db config can make login itself
# unusable. Messages carry file and key names only, never secret values.
@blueprint.route("/")
def index():
    issues = current_app.config["CONFIG_ISSUES_PROVIDER"]()
    return render_template("config_issues.html", issues=issues)
