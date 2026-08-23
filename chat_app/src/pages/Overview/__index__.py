from flask import Blueprint, render_template

from src.services.authz import require_login

blueprint = Blueprint("overview", __name__, template_folder=".")

PAGE_PERMISSION = None


@blueprint.route("/")
@require_login()
def index():
    return render_template("overview.html")
