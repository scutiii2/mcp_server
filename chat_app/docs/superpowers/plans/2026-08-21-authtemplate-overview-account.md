# AuthTemplate Overview & Account Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the post-login landing page (Overview — page picker, no sidebar) and the self-service profile page (Account — view/edit own username/email/password), plus the shared authenticated-page chrome (expandable/collapsible sidebar) that every page except Overview now uses. This is Phase 5 of a multi-phase build, depending on the models (Phase 1), security pipeline (Phase 2), auth core (Phase 3), and Admin page (Phase 4: [2026-08-21-authtemplate-admin-invites.md](2026-08-21-authtemplate-admin-invites.md)).

**Architecture:** Each page blueprint module gains an optional `PAGE_PERMISSION` attribute (a permission string, or `None` for "any authenticated account"). `pages/__index__.py`'s `register_pages()` reads it while registering blueprints, builds `app.config["PAGES"]`, and registers a `nav_pages` context processor so every template gets the current account's accessible-page list for free — no page route computes this itself. Overview renders that list as tiles; the shared `sidebar.html` (included by every other authenticated page) renders it as nav links. `authz.py` gains `require_login()` (authenticated, no specific permission) and `register_permission()` (declare a permission without decorator-enforcing it, needed by Account's manually-checked `account.edit` gate).

**Tech Stack:** Same as prior phases — Flask blueprints/Jinja2, Flask-Login, pytest with Flask's test client. No new dependencies.

**Spec:** [docs/superpowers/specs/2026-08-21-authtemplate-design.md](../specs/2026-08-21-authtemplate-design.md)

## Global Constraints

- Overview (`pages/Overview/`, served at `/`) shows a tile for every page the current account has permission to reach, computed by checking each registered blueprint's declared permission requirement against the account's permission set (spec §12).
- Sidebar hidden on Overview; instead Overview shows the logged-in account's username plus Logout in the upper-right corner (spec §12).
- Every *other* page gets an expandable/collapsible sidebar listing the same permitted pages, with username + Logout pinned at the bottom (spec §12).
- `pages/__shared__/` holds `base.html`, `sidebar.html`, `shared.js`, `shared.css` (spec §4) — not auto-registered as a page (spec §11).
- Permissions are namespaced strings discovered as pages declare them (spec §5, §10) — `account.edit` (spec §5's own example) must go through the same registry as every other permission, even though Account checks it manually rather than via `@require_permission`.
- `src/run.py`'s `create_app(config: dict | None = None) -> Flask` signature does not change.
- No placeholders, no TODOs.

---

## File Structure

```
src/
  services/
    authz.py                        # MODIFIED: + register_permission(), require_login()
    auth_service.py                  # MODIFIED: + update_account_profile()
  pages/
    __index__.py                      # MODIFIED: page registry + nav_pages context processor
    README.md                          # MODIFIED: Overview/Account added to index
    __shared__/
      base.html                        # MODIFIED: {% block sidebar %}, shared.css/js links
      sidebar.html                      # NEW
      shared.css                         # NEW
      shared.js                           # NEW
    Auth/
      __index__.py                         # MODIFIED: + PAGE_PERMISSION = None
    Admin/
      __index__.py                          # MODIFIED: + PAGE_PERMISSION = "admin.roles.manage"
      view.html                              # MODIFIED: + sidebar block
    Overview/
      __init__.py                             # NEW, empty
      __index__.py                             # NEW
      view.html                                 # NEW
      README.md                                  # NEW
    Account/
      __init__.py                                 # NEW, empty
      __index__.py                                 # NEW
      view.html                                     # NEW
      README.md                                      # NEW
  run.py                                             # MODIFIED: static_folder/static_url_path for shared.css/js
tests/
  test_authz.py                                       # MODIFIED: + register_permission/require_login tests
  test_auth_service.py                                 # MODIFIED: + update_account_profile tests
  test_pages_index.py                                   # MODIFIED: + page registry test
  test_overview_page.py                                  # NEW
  test_account_page.py                                    # NEW
```

---

### Task 1: `authz.py` — `register_permission()` + `require_login()`

**Files:**
- Modify: `src/services/authz.py`
- Modify: `tests/test_authz.py`

**Interfaces:**
- Produces: `register_permission(name: str) -> None` (adds to the registry without wrapping a view), `require_login()` (decorator factory: 401 if unauthenticated, no permission check) in `src/services/authz.py`. `require_permission()` now calls `register_permission()` internally instead of touching `_REGISTERED_PERMISSIONS` directly — same net effect, no signature change.
- Later tasks: Task 2 (`pages/__index__.py`) doesn't need these directly. Task 4 (Overview) uses `require_login()`. Task 5 (Account) uses both `require_login()` and `register_permission()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_authz.py` (update the import block at the top first):

```python
from src.services.authz import (
    account_permissions,
    has_permission,
    register_permission,
    registered_permissions,
    require_login,
    require_permission,
)
```

Add these test functions:

```python
def test_register_permission_adds_to_registry():
    register_permission("standalone.registered_permission")

    assert "standalone.registered_permission" in registered_permissions()


def test_require_login_blocks_unauthenticated_request(app):
    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Account, int(user_id))

    @app.route("/needs-login")
    @require_login()
    def needs_login():
        return "ok"

    client = app.test_client()
    response = client.get("/needs-login")

    assert response.status_code == 401


def test_require_login_allows_any_authenticated_account(app):
    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Account, int(user_id))

    @app.route("/login-as3/<int:account_id>")
    def login_as3(account_id):
        account = db.session.get(Account, account_id)
        login_user(account)
        return "logged in"

    @app.route("/needs-login2")
    @require_login()
    def needs_login2():
        return "ok"

    with app.app_context():
        account = Account(username="karen", email="karen@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    client.get(f"/login-as3/{account_id}")
    response = client.get("/needs-login2")

    assert response.status_code == 200
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_authz.py -v`
Expected: FAIL with `ImportError: cannot import name 'register_permission' from 'src.services.authz'`

- [ ] **Step 3: Implement (full replacement of `authz.py`)**

`src/services/authz.py`:
```python
from functools import wraps

from flask import abort
from flask_login import current_user

_REGISTERED_PERMISSIONS: set[str] = set()


def register_permission(name: str) -> None:
    _REGISTERED_PERMISSIONS.add(name)


def registered_permissions() -> set[str]:
    return set(_REGISTERED_PERMISSIONS)


def account_permissions(account) -> set[str]:
    permissions: set[str] = set()
    for role in account.roles:
        for permission in role.permissions:
            permissions.add(permission.name)
    return permissions


def has_permission(account, permission_name: str) -> bool:
    return permission_name in account_permissions(account)


def require_login():
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            return view_func(*args, **kwargs)

        return wrapped

    return decorator


def require_permission(permission_name: str):
    register_permission(permission_name)

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if not has_permission(current_user, permission_name):
                abort(403)
            return view_func(*args, **kwargs)

        return wrapped

    return decorator
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_authz.py -v`
Expected: PASS (9 tests — the original 6 plus these 3)

- [ ] **Step 5: Commit**

```bash
git add src/services/authz.py tests/test_authz.py
git commit -m "feat: add register_permission and require_login to authz"
```

---

### Task 2: Page registry + `nav_pages` context processor

**Files:**
- Modify: `src/pages/__index__.py`
- Modify: `src/pages/Auth/__index__.py`
- Modify: `src/pages/Admin/__index__.py`
- Modify: `tests/test_pages_index.py`

**Interfaces:**
- Consumes: `has_permission` from `src.services.authz` (Phase 3/Task 1).
- Produces: `register_pages(app, ...)` now also sets `app.config["PAGES"]` (a `list[dict]`, each `{"name": str, "url_prefix": str, "permission": str | None}`) and registers an `app.context_processor` that injects `nav_pages` (same shape, filtered to accessible pages excluding `"Overview"` and `"Auth"`) into every template render — empty for anonymous requests.
- A page module can now declare `PAGE_PERMISSION: str | None` at module level; `register_pages` reads it via `getattr(module, "PAGE_PERMISSION", None)`.
- Later tasks: Task 3's `sidebar.html` and Task 4's Overview template both read `nav_pages` directly from template context (no Python-side change needed in those tasks beyond what this task provides).

- [ ] **Step 1: Declare `PAGE_PERMISSION` on the existing pages**

`src/pages/Auth/__index__.py` — add near the top, after the `blueprint = Blueprint(...)` block:
```python
PAGE_PERMISSION = None
```

`src/pages/Admin/__index__.py` — add in the same spot:
```python
PAGE_PERMISSION = "admin.roles.manage"
```

- [ ] **Step 2: Write the failing test**

Update the import line at the top of `tests/test_pages_index.py`:
```python
from src.pages.__index__ import discover_page_modules, register_pages
```

Add:
```python
def test_register_pages_builds_page_registry_with_permissions():
    from flask import Flask

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    register_pages(app)

    pages_by_name = {p["name"]: p for p in app.config["PAGES"]}
    assert pages_by_name["Auth"]["permission"] is None
    assert pages_by_name["Admin"]["permission"] == "admin.roles.manage"
    assert pages_by_name["Admin"]["url_prefix"] == "/admin"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_pages_index.py -v`
Expected: FAIL — `app.config["PAGES"]` raises `KeyError` (registry not built yet)

- [ ] **Step 4: Implement (full replacement of `pages/__index__.py`)**

`src/pages/__index__.py`:
```python
import importlib
from pathlib import Path

from flask import Flask
from flask_login import current_user

from src.services.authz import has_permission

PAGES_DIR = Path(__file__).resolve().parent


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
    app: Flask, pages_dir: Path = PAGES_DIR, package_prefix: str = "src.pages"
) -> None:
    pages = []
    for folder_name in discover_page_modules(pages_dir):
        module = importlib.import_module(f"{package_prefix}.{folder_name}.__index__")
        blueprint = getattr(module, "blueprint")
        page_permission = getattr(module, "PAGE_PERMISSION", None)
        url_prefix = _url_prefix_for(folder_name)
        app.register_blueprint(blueprint, url_prefix=url_prefix)
        pages.append({"name": folder_name, "url_prefix": url_prefix, "permission": page_permission})

    app.config["PAGES"] = pages

    @app.context_processor
    def inject_nav_pages():
        if not current_user.is_authenticated:
            return {}
        nav_pages = [
            p
            for p in app.config.get("PAGES", [])
            if p["name"] not in ("Overview", "Auth")
            and (p["permission"] is None or has_permission(current_user, p["permission"]))
        ]
        return {"nav_pages": nav_pages}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_pages_index.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full suite to verify nothing broke**

Run: `pytest -v`
Expected: PASS (all 121 pre-existing tests, plus the 2 above and Task 1's 3 new ones — 126 total). Admin's and Auth's page tests are unaffected: adding a module-level `PAGE_PERMISSION` constant doesn't change route behavior.

- [ ] **Step 7: Commit**

```bash
git add src/pages/__index__.py src/pages/Auth/__index__.py src/pages/Admin/__index__.py tests/test_pages_index.py
git commit -m "feat: add page registry and nav_pages context processor"
```

---

### Task 3: Shared sidebar chrome

**Files:**
- Modify: `src/pages/__shared__/base.html`
- Create: `src/pages/__shared__/sidebar.html`
- Create: `src/pages/__shared__/shared.css`
- Create: `src/pages/__shared__/shared.js`
- Modify: `src/pages/Admin/view.html`

**Interfaces:**
- Consumes: `nav_pages` (Task 2's context processor), `current_user` (Flask-Login), `url_for('auth.logout')` (Phase 3).
- Produces: a `{% block sidebar %}{% endblock %}` in `base.html` (empty by default — Auth's login/register pages, which never override it, keep rendering with no sidebar, unchanged from Phase 3); `sidebar.html`, included via `{% block sidebar %}{% include "sidebar.html" %}{% endblock %}` by any authenticated page that wants one.
- Later tasks: Task 4 (Overview) deliberately does **not** override the sidebar block. Task 5 (Account) does.

- [ ] **Step 1: Modify `base.html`**

`src/pages/__shared__/base.html` (full replacement):
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{% block title %}AuthTemplate{% endblock %}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="{{ url_for('static', filename='shared.css') }}">
</head>
<body>
  {% block sidebar %}{% endblock %}
  <main>
    {% block content %}{% endblock %}
  </main>
  <script src="{{ url_for('static', filename='shared.js') }}"></script>
</body>
</html>
```

- [ ] **Step 2: Write `sidebar.html`, `shared.css`, `shared.js`**

`src/pages/__shared__/sidebar.html`:
```html
<nav class="sidebar" id="sidebar">
  <button type="button" id="sidebar-toggle" aria-expanded="true" aria-controls="sidebar-links">☰</button>
  <ul class="nav-links" id="sidebar-links">
    {% for page in nav_pages %}
    <li><a href="{{ page.url_prefix }}">{{ page.name }}</a></li>
    {% endfor %}
  </ul>
  <div class="sidebar-footer">
    <span class="username">{{ current_user.username }}</span>
    <a href="{{ url_for('auth.logout') }}">Logout</a>
  </div>
</nav>
```

`src/pages/__shared__/shared.css`:
```css
body {
  font-family: system-ui, sans-serif;
  margin: 0;
  display: flex;
}

.sidebar {
  width: 200px;
  border-right: 1px solid #ccc;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  box-sizing: border-box;
}

.sidebar.collapsed .nav-links,
.sidebar.collapsed .sidebar-footer {
  display: none;
}

.sidebar .nav-links {
  list-style: none;
  padding: 0;
  flex-grow: 1;
}

.sidebar .nav-links li {
  margin-bottom: 0.5rem;
}

.sidebar-footer {
  border-top: 1px solid #ccc;
  padding-top: 0.5rem;
}

main {
  padding: 1.5rem;
  flex-grow: 1;
}

.overview-header {
  display: flex;
  justify-content: flex-end;
  gap: 1rem;
  align-items: center;
  margin-bottom: 1rem;
}

.tiles {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}

.tile {
  display: block;
  border: 1px solid #ccc;
  border-radius: 8px;
  padding: 1.5rem;
  min-width: 120px;
  text-align: center;
  text-decoration: none;
  color: inherit;
}
```

`src/pages/__shared__/shared.js`:
```javascript
document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.getElementById("sidebar-toggle");
  const sidebar = document.getElementById("sidebar");
  if (!toggle || !sidebar) return;
  toggle.addEventListener("click", () => {
    const collapsed = sidebar.classList.toggle("collapsed");
    toggle.setAttribute("aria-expanded", String(!collapsed));
  });
});
```

- [ ] **Step 3: Add the sidebar to the Admin page**

Modify `src/pages/Admin/view.html` — add one line right after `{% block title %}Admin{% endblock %}`:
```html
{% block sidebar %}{% include "sidebar.html" %}{% endblock %}
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -v`
Expected: PASS (126 tests, unchanged — `url_for('static', ...)` builds a URL string against Flask's always-registered default `static` endpoint even in test apps that never configured a real `static_folder`; none of the existing tests fetch that URL, they only check rendered HTML, so this doesn't require touching any existing test app builder)

- [ ] **Step 5: Commit**

```bash
git add src/pages/__shared__/base.html src/pages/__shared__/sidebar.html src/pages/__shared__/shared.css src/pages/__shared__/shared.js src/pages/Admin/view.html
git commit -m "feat: add shared collapsible sidebar chrome"
```

---

### Task 4: Overview page

**Files:**
- Create: `src/pages/Overview/__init__.py` (empty)
- Create: `src/pages/Overview/__index__.py`
- Create: `src/pages/Overview/view.html`
- Create: `src/pages/Overview/README.md`
- Test: `tests/test_overview_page.py`

**Interfaces:**
- Consumes: `require_login` from `src.services.authz` (Task 1); `nav_pages` from the context processor (Task 2); `register_pages` from `src.pages.__index__` (Task 2).
- Produces: `blueprint` (Flask `Blueprint` named `"overview"`) exposing `GET /` — registered at url prefix `/` (the `Overview` special case in `_url_prefix_for`), `PAGE_PERMISSION = None`.

- [ ] **Step 1: Write `pages/Overview/__index__.py` and `view.html`**

`src/pages/Overview/__init__.py`: empty file.

`src/pages/Overview/__index__.py`:
```python
from flask import Blueprint, render_template

from src.services.authz import require_login

blueprint = Blueprint("overview", __name__, template_folder=".")

PAGE_PERMISSION = None


@blueprint.route("/")
@require_login()
def index():
    return render_template("view.html")
```

`src/pages/Overview/view.html`:
```html
{% extends "base.html" %}
{% block title %}Overview{% endblock %}
{% block content %}
<header class="overview-header">
  <span class="username">{{ current_user.username }}</span>
  <a href="{{ url_for('auth.logout') }}">Logout</a>
</header>
<h1>Overview</h1>
<div class="tiles">
  {% for page in nav_pages %}
  <a class="tile" href="{{ page.url_prefix }}">{{ page.name }}</a>
  {% endfor %}
</div>
{% endblock %}
```

(No `{% block sidebar %}` override — it stays empty, per spec §12: Overview has no sidebar.)

- [ ] **Step 2: Write `pages/Overview/README.md`**

```markdown
# pages/Overview/

Post-login landing page and page picker (spec §12). URL: `/` (the one
exception to the folder-name-lowercased URL prefix rule).

## Routes

- `GET /` — shows a tile for every page the current account can reach
  (any page with `PAGE_PERMISSION = None`, or one the account holds the
  permission for), computed by `pages/__index__.py`'s `nav_pages`
  context processor. No sidebar here — Overview *is* the page picker,
  so it shows the account's username and a Logout link in the
  upper-right corner instead (every other page gets the sidebar).

## Permissions

None beyond being logged in (`authz.require_login()`).
```

- [ ] **Step 3: Write the failing tests**

`tests/test_overview_page.py`:
```python
from pathlib import Path

from flask import Flask

from src.models import Account, Permission, Role, db
from src.pages.__index__ import register_pages
from src.services.auth_service import init_login_manager
from src.services.email_service import init_mail

_SHARED_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "pages" / "__shared__"


def _build_overview_test_app(tmp_path):
    app = Flask(
        __name__,
        template_folder=str(_SHARED_TEMPLATES_DIR),
        static_folder=str(_SHARED_TEMPLATES_DIR),
        static_url_path="/shared/static",
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'overview_test.db'}"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SECRET_KEY"] = "test-secret"
    app.config["MAIL_SUPPRESS_SEND"] = True

    db.init_app(app)
    with app.app_context():
        db.create_all()

    init_login_manager(app)
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    init_mail(app, secrets_dir)
    register_pages(app)

    return app


def _login_as(client, account_id):
    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(account_id)
        flask_session["_fresh"] = True


def test_overview_requires_authentication(tmp_path):
    app = _build_overview_test_app(tmp_path)
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 401


def test_overview_shows_only_accessible_pages(tmp_path):
    app = _build_overview_test_app(tmp_path)

    with app.app_context():
        account = Account(username="viewer", email="viewer@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/")

    assert response.status_code == 200
    assert b'href="/account"' in response.data
    assert b'href="/admin"' not in response.data
    assert b'href="/auth"' not in response.data


def test_overview_shows_admin_tile_for_admin_account(tmp_path):
    app = _build_overview_test_app(tmp_path)

    with app.app_context():
        role = Role(name="Administrator")
        permission = Permission(name="admin.roles.manage")
        role.permissions.append(permission)
        account = Account(username="admin_user", email="admin_user@example.com", password_hash="hashed")
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/")

    assert response.status_code == 200
    assert b'href="/admin"' in response.data


def test_overview_has_no_sidebar(tmp_path):
    app = _build_overview_test_app(tmp_path)

    with app.app_context():
        account = Account(username="nosidebar", email="nosidebar@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/")

    assert response.status_code == 200
    assert b'id="sidebar"' not in response.data
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `pytest tests/test_overview_page.py -v`
Expected: FAIL with `ModuleNotFoundError` (no `Overview` page yet) or a 404, since `register_pages` won't find it

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_overview_page.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add src/pages/Overview tests/test_overview_page.py
git commit -m "feat: add Overview page (post-login landing / page picker)"
```

---

### Task 5: Account page (self-service profile)

**Files:**
- Modify: `src/services/auth_service.py`
- Modify: `tests/test_auth_service.py`
- Create: `src/pages/Account/__init__.py` (empty)
- Create: `src/pages/Account/__index__.py`
- Create: `src/pages/Account/view.html`
- Create: `src/pages/Account/README.md`
- Test: `tests/test_account_page.py`

**Interfaces:**
- Consumes: `has_permission`, `register_permission`, `require_login` from `src.services.authz` (Task 1); `check_password_hash`/`generate_password_hash` from Werkzeug (already used elsewhere in `auth_service.py`).
- Produces: `update_account_profile(db_session, account: Account, current_password: str, new_email: str | None, new_password: str | None) -> bool` appended to `src/services/auth_service.py`. `blueprint` (Flask `Blueprint` named `"account"`) exposing `GET/POST /` (prefixed `/account`), `PAGE_PERMISSION = None`.

- [ ] **Step 1: Write the failing test for `update_account_profile`**

Update the top import line of `tests/test_auth_service.py`:
```python
from werkzeug.security import check_password_hash, generate_password_hash
```

Add:
```python
def test_update_account_profile_succeeds_with_correct_password(app):
    with app.app_context():
        account = Account(
            username="profile_user",
            email="old@example.com",
            password_hash=generate_password_hash("current-pw"),
        )
        db.session.add(account)
        db.session.commit()

        success = auth_service.update_account_profile(
            db.session, account, "current-pw", "new@example.com", None
        )

        assert success is True
        assert account.email == "new@example.com"


def test_update_account_profile_fails_with_wrong_password(app):
    with app.app_context():
        account = Account(
            username="profile_user2",
            email="unchanged@example.com",
            password_hash=generate_password_hash("current-pw"),
        )
        db.session.add(account)
        db.session.commit()

        success = auth_service.update_account_profile(
            db.session, account, "wrong-pw", "new@example.com", None
        )

        assert success is False
        assert account.email == "unchanged@example.com"


def test_update_account_profile_updates_password_hash(app):
    with app.app_context():
        account = Account(
            username="profile_user3",
            email="profile_user3@example.com",
            password_hash=generate_password_hash("old-pw"),
        )
        db.session.add(account)
        db.session.commit()

        auth_service.update_account_profile(db.session, account, "old-pw", None, "new-pw")

        assert check_password_hash(account.password_hash, "new-pw")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_auth_service.py -v`
Expected: FAIL with `AttributeError: module 'src.services.auth_service' has no attribute 'update_account_profile'`

- [ ] **Step 3: Append `update_account_profile` to `auth_service.py`**

Add to the end of `src/services/auth_service.py` (no changes to existing content — this is a pure addition):
```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_auth_service.py -v`
Expected: PASS (12 tests — the original 9 plus these 3)

- [ ] **Step 5: Write the Account page**

`src/pages/Account/__init__.py`: empty file.

`src/pages/Account/__index__.py`:
```python
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from src.models import db
from src.services import auth_service
from src.services.authz import has_permission, register_permission, require_login

blueprint = Blueprint("account", __name__, template_folder=".")

PAGE_PERMISSION = None

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
            flash("Profile updated")
        else:
            flash("Current password is incorrect")
        return redirect(url_for("account.profile"))

    return render_template("view.html", can_edit=can_edit)
```

`src/pages/Account/view.html`:
```html
{% extends "base.html" %}
{% block title %}Account{% endblock %}
{% block sidebar %}{% include "sidebar.html" %}{% endblock %}
{% block content %}
<h1>Account</h1>

{% with messages = get_flashed_messages() %}
  {% if messages %}
  <ul class="flash">
    {% for message in messages %}<li>{{ message }}</li>{% endfor %}
  </ul>
  {% endif %}
{% endwith %}

<p>Username: {{ current_user.username }}</p>
<p>Email: {{ current_user.email }}</p>

{% if can_edit %}
<form method="post" action="{{ url_for('account.profile') }}">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() if csrf_token is defined else '' }}">
  <label for="email">New email</label>
  <input type="email" id="email" name="email" placeholder="{{ current_user.email }}">
  <label for="new_password">New password</label>
  <input type="password" id="new_password" name="new_password">
  <label for="current_password">Current password (required to save)</label>
  <input type="password" id="current_password" name="current_password" required>
  <button type="submit">Save Changes</button>
</form>
{% else %}
<p>Contact an administrator to update your profile.</p>
{% endif %}
{% endblock %}
```

`src/pages/Account/README.md`:
```markdown
# pages/Account/

Self-service profile view/edit (spec §5's own example permission,
`account.edit`). URL prefix: `/account`.

## Routes

- `GET /account/` — view your own username/email. Everyone logged in
  can reach this page (`PAGE_PERMISSION = None`).
- `POST /account/` — update email and/or password (`current_password`
  required to authorize the change, verified via
  `auth_service.update_account_profile`). Requires `account.edit` —
  registered via `authz.register_permission()` at import time (checked
  manually with `authz.has_permission()`, not the `@require_permission`
  decorator, since GET and POST share one route and only POST needs the
  gate).

## Permissions

`account.edit` — **flagged default**: new accounts get no roles at
registration (spec §7), so a fresh account cannot edit its own profile
until an admin grants it. This matches the template's "admin controls
everything explicitly" philosophy, but is worth reconsidering per
project — a project might prefer everyone can always edit their own
profile, in which case drop the permission check here entirely.
```

- [ ] **Step 6: Write the failing integration tests**

`tests/test_account_page.py`:
```python
from pathlib import Path

from flask import Flask
from werkzeug.security import check_password_hash, generate_password_hash

from src.models import Account, Permission, Role, db
from src.pages.__index__ import register_pages
from src.services.auth_service import init_login_manager
from src.services.email_service import init_mail

_SHARED_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "pages" / "__shared__"


def _build_account_test_app(tmp_path):
    app = Flask(
        __name__,
        template_folder=str(_SHARED_TEMPLATES_DIR),
        static_folder=str(_SHARED_TEMPLATES_DIR),
        static_url_path="/shared/static",
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'account_test.db'}"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SECRET_KEY"] = "test-secret"
    app.config["MAIL_SUPPRESS_SEND"] = True

    db.init_app(app)
    with app.app_context():
        db.create_all()

    init_login_manager(app)
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    init_mail(app, secrets_dir)
    register_pages(app)

    return app


def _login_as(client, account_id):
    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(account_id)
        flask_session["_fresh"] = True


def test_account_page_requires_authentication(tmp_path):
    app = _build_account_test_app(tmp_path)
    client = app.test_client()

    response = client.get("/account/")

    assert response.status_code == 401


def test_account_page_renders_read_only_without_edit_permission(tmp_path):
    app = _build_account_test_app(tmp_path)

    with app.app_context():
        account = Account(
            username="plain",
            email="plain@example.com",
            password_hash=generate_password_hash("secret123"),
        )
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/account/")

    assert response.status_code == 200
    assert b"plain@example.com" in response.data
    assert b"Contact an administrator" in response.data


def test_account_page_post_rejected_without_edit_permission(tmp_path):
    app = _build_account_test_app(tmp_path)

    with app.app_context():
        account = Account(
            username="noedit",
            email="noedit@example.com",
            password_hash=generate_password_hash("secret123"),
        )
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    response = client.post(
        "/account/",
        data={"current_password": "secret123", "email": "changed@example.com"},
    )

    assert response.status_code == 302
    with app.app_context():
        refreshed = db.session.get(Account, account_id)
        assert refreshed.email == "noedit@example.com"


def test_account_page_updates_email_with_edit_permission_and_correct_password(tmp_path):
    app = _build_account_test_app(tmp_path)

    with app.app_context():
        role = Role(name="editor_role")
        permission = Permission(name="account.edit")
        role.permissions.append(permission)
        account = Account(
            username="editor",
            email="editor@example.com",
            password_hash=generate_password_hash("secret123"),
        )
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    response = client.post(
        "/account/",
        data={"current_password": "secret123", "email": "updated@example.com"},
    )

    assert response.status_code == 302
    with app.app_context():
        refreshed = db.session.get(Account, account_id)
        assert refreshed.email == "updated@example.com"


def test_account_page_rejects_wrong_current_password(tmp_path):
    app = _build_account_test_app(tmp_path)

    with app.app_context():
        role = Role(name="editor_role2")
        permission = Permission(name="account.edit")
        role.permissions.append(permission)
        account = Account(
            username="editor2",
            email="editor2@example.com",
            password_hash=generate_password_hash("secret123"),
        )
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    response = client.post(
        "/account/",
        data={"current_password": "wrong-password", "email": "shouldnotchange@example.com"},
    )

    assert response.status_code == 302
    with app.app_context():
        refreshed = db.session.get(Account, account_id)
        assert refreshed.email == "editor2@example.com"


def test_account_page_updates_password_with_edit_permission(tmp_path):
    app = _build_account_test_app(tmp_path)

    with app.app_context():
        role = Role(name="editor_role3")
        permission = Permission(name="account.edit")
        role.permissions.append(permission)
        account = Account(
            username="editor3",
            email="editor3@example.com",
            password_hash=generate_password_hash("old-password"),
        )
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    _login_as(client, account_id)

    client.post(
        "/account/",
        data={"current_password": "old-password", "new_password": "new-password"},
    )

    with app.app_context():
        refreshed = db.session.get(Account, account_id)
        assert check_password_hash(refreshed.password_hash, "new-password")
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/test_account_page.py -v`
Expected: PASS (6 tests)

- [ ] **Step 8: Commit**

```bash
git add src/services/auth_service.py tests/test_auth_service.py src/pages/Account tests/test_account_page.py
git commit -m "feat: add Account page (self-service profile view/edit)"
```

---

### Task 6: Wire real static assets + docs + full verification

**Files:**
- Modify: `src/run.py`
- Modify: `src/pages/README.md`

**Interfaces:**
- `create_app(config: dict | None = None) -> Flask` signature unchanged.

- [ ] **Step 1: Modify `src/run.py`**

**Before editing, `Read` the current file** to confirm exact surrounding lines. Change the `Flask(...)` constructor call to also serve `shared.css`/`shared.js` for real (Task 3 relied on Flask's *default* `static` endpoint existing for URL-building in tests, but the actual files only get served if `static_folder` points at `__shared__`):

```python
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "pages" / "__shared__"),
        static_folder=str(BASE_DIR / "pages" / "__shared__"),
        static_url_path="/shared/static",
    )
```

This replaces the single-line `app = Flask(__name__, template_folder=str(BASE_DIR / "pages" / "__shared__"))` call. Nothing else in `run.py` changes.

- [ ] **Step 2: Update `src/pages/README.md`'s index**

Replace the "## Pages" section:
```markdown
## Pages

- [`Auth/`](Auth/README.md) — the merged login/registration/logout flow.
- [`Admin/`](Admin/README.md) — role/permission/account administration
  and invite generation.
- [`Overview/`](Overview/README.md) — post-login landing page / page
  picker.
- [`Account/`](Account/README.md) — self-service profile view/edit.
```

- [ ] **Step 3: Run the full test suite**

Run: `pytest -v`
Expected: PASS (every test from Phases 1-4 plus this plan's Tasks 1-5 — 139 total: 121 pre-existing + 3 (Task 1) + 2 (Task 2) + 0 (Task 3, no new tests) + 4 (Task 4) + 3 + 6 (Task 5))

- [ ] **Step 4: Commit**

```bash
git add src/run.py src/pages/README.md
git commit -m "feat: serve shared.css/shared.js as real static assets"
```

---

## Out of Scope for This Plan (later phases)

- Root `README.md` — Phase 6, now that Overview/Account/Admin/Auth all exist and the abstract permission/role/registration model can be documented accurately end-to-end.
- `src/utils/validators.py` (input validation helpers referenced in `src/utils/README.md` since Phase 1 but never built) — not required by anything in this plan; add when a concrete validation need appears.
- Splitting invite generation onto its own page reachable by an `auth.invite`-only role without `admin.roles.manage` (noted in Phase 4's `pages/Admin/README.md`) — still not addressed here.
