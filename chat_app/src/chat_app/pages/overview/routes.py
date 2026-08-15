"""Landing page at "/" - the app's entry point.

This blueprint owns everything under ``pages/overview/`` - both its route
and its own ``template/`` folder. See ``pages/chat/routes.py`` and
``app.py`` for why the static/template wiring looks the way it does.

The list of pages below is a plain, hand-written list, not a reflection of
anything registered elsewhere. That's deliberate: unlike the tool/resource
catalogs on the capabilities page (which are never hardcoded because they
mirror a live external server that can change independently of this
codebase), page routing is fixed by what's registered in ``app.py`` - a
manual, by-hand step per page already, same as adding a blueprint there in
the first place. A static list is the right level of engineering for that;
an auto-discovery mechanism would be solving a problem that doesn't exist.
"""

from __future__ import annotations

from flask import Blueprint, render_template


overview_bp = Blueprint(
    "overview",
    __name__,
    static_folder="template",
    static_url_path="/pages/overview/assets",
)


@overview_bp.get("/")
def index():
    return render_template("overview/index.html")
