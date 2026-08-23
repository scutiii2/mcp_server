from flask import Blueprint, render_template

from src.services.authz import require_login

blueprint = Blueprint("sample", __name__, template_folder=".")

PAGE_PERMISSION = None
PAGE_DESCRIPTION = "A working example page — copy this folder as a starting point for a new one."


@blueprint.route("/")
@require_login()
def index():
    return render_template("sample.html")
