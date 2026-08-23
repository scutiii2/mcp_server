import importlib
from pathlib import Path

from flask import Flask, request, url_for
from flask_login import current_user

from src.services.authz import has_permission

PAGES_DIR = Path(__file__).resolve().parent

_ACCOUNT_MENU_PAGES = ("Account", "Admin")
_LOGO_FILENAME = "logo.png"


def discover_page_modules(pages_dir: Path = PAGES_DIR) -> list[str]:
    names = []
    for entry in sorted(Path(pages_dir).iterdir()):
        if not entry.is_dir():
            continue
        if entry.name == "__shared__" or entry.name.startswith("__pycache__"):
            continue
        if (entry / "__index__.py").exists():
            names.append(entry.name)
    return names


def _url_prefix_for(folder_name: str) -> str:
    if folder_name.lower() == "overview":
        return "/"
    return f"/{folder_name.lower()}"


def register_pages(
    app: Flask, pages_dir: Path = PAGES_DIR, package_prefix: str = "src.pages", csrf=None
) -> None:
    pages = []
    for folder_name in discover_page_modules(pages_dir):
        module = importlib.import_module(f"{package_prefix}.{folder_name}.__index__")
        blueprint = getattr(module, "blueprint")
        page_permission = getattr(module, "PAGE_PERMISSION", None)
        page_description = getattr(module, "PAGE_DESCRIPTION", None)
        page_layout = getattr(module, "PAGE_LAYOUT", "full")
        url_prefix = _url_prefix_for(folder_name)
        app.register_blueprint(blueprint, url_prefix=url_prefix)
        if csrf is not None and getattr(module, "CSRF_EXEMPT", False):
            csrf.exempt(blueprint)
        pages.append(
            {
                "name": folder_name,
                "url_prefix": url_prefix,
                "permission": page_permission,
                "description": page_description,
                "layout": page_layout,
            }
        )

    app.config["PAGES"] = pages
    app.config["APP_LOGO_AVAILABLE"] = (Path(app.static_folder) / _LOGO_FILENAME).exists()

    @app.context_processor
    def inject_page_layout():
        layouts = {p["name"].lower(): p.get("layout", "full") for p in app.config.get("PAGES", [])}
        return {"page_layout": layouts.get(request.blueprint, "full")}

    @app.context_processor
    def inject_nav_pages():
        if not current_user.is_authenticated:
            return {}

        def _visible(p):
            perm = p["permission"]
            if perm is None:
                return True
            if isinstance(perm, (list, tuple)):
                return any(has_permission(current_user, name) for name in perm)
            return has_permission(current_user, perm)

        all_pages = app.config.get("PAGES", [])
        nav_pages = [
            p
            for p in all_pages
            if p["name"] not in ("Overview", "Auth", *_ACCOUNT_MENU_PAGES) and _visible(p)
        ]
        account_menu_pages = [
            p for p in all_pages if p["name"] in _ACCOUNT_MENU_PAGES and _visible(p)
        ]
        app_logo_url = (
            url_for("static", filename=_LOGO_FILENAME)
            if app.config.get("APP_LOGO_AVAILABLE")
            else None
        )
        return {
            "nav_pages": nav_pages,
            "account_menu_pages": account_menu_pages,
            "app_logo_url": app_logo_url,
        }
