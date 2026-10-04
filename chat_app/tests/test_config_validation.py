import json
import shutil
from pathlib import Path

from flask import Flask

from src.services.config_validation import collect_issues, install_config_guard

REAL_APP_DIR = Path(__file__).resolve().parent.parent


def _make_app_dir(tmp_path):
    for sub in ("configs", "secrets"):
        (tmp_path / sub).mkdir()
        for example in (REAL_APP_DIR / sub).glob("*.example"):
            shutil.copyfile(example, tmp_path / sub / example.name)
    (tmp_path / "secrets" / "secret_app.env.example").write_text("SECRET_KEY=" + "k" * 32)
    (tmp_path / "secrets" / "secret_internal_api.env.example").write_text("INTERNAL_API_TOKEN=" + "t" * 32)
    return tmp_path


def test_valid_examples_have_no_issues(tmp_path):
    assert collect_issues(_make_app_dir(tmp_path)) == []


def test_seeded_blank_secrets_are_reported(tmp_path):
    app_dir = _make_app_dir(tmp_path)
    (app_dir / "secrets" / "secret_app.env.example").write_text("SECRET_KEY=\n")

    issues = collect_issues(app_dir)

    assert [(i.file, i.key) for i in issues] == [("secret_app.env", "SECRET_KEY")]


def test_bad_json_and_bad_types_reported(tmp_path):
    app_dir = _make_app_dir(tmp_path)
    (app_dir / "configs" / "config_app.json.example").write_text("{not json")
    (app_dir / "configs" / "config_usage_limits.json.example").write_text(
        json.dumps({"six_hour_token_limit": "many", "weekly_token_limit": 1, "max_context_tokens_per_chat": 1})
    )

    found = {(i.file, i.key) for i in collect_issues(app_dir)}

    assert ("config_app.json", "-") in found
    assert ("config_usage_limits.json", "six_hour_token_limit") in found


def test_placeholder_reported_without_leaking_value(tmp_path):
    app_dir = _make_app_dir(tmp_path)
    (app_dir / "secrets" / "secret_internal_api.env.example").write_text("INTERNAL_API_TOKEN=changeme")

    issues = collect_issues(app_dir)

    assert [(i.key, i.message) for i in issues] == [("INTERNAL_API_TOKEN", "is still a placeholder value")]


def test_guard_redirects_until_fixed(tmp_path):
    app_dir = _make_app_dir(tmp_path)
    (app_dir / "secrets" / "secret_app.env.example").write_text("SECRET_KEY=\n")
    from src.pages.ConfigIssues.__index__ import blueprint

    shared = str(REAL_APP_DIR / "src" / "pages" / "__shared__")
    app = Flask(__name__, template_folder=shared, static_folder=shared, static_url_path="/shared/static")
    app.register_blueprint(blueprint, url_prefix="/configissues")
    app.add_url_rule("/x", "x", lambda: "ok")
    install_config_guard(app, app_dir)
    client = app.test_client()

    response = client.get("/x")
    assert response.status_code == 302 and response.headers["Location"].endswith("/configissues/")
    assert b"SECRET_KEY" in client.get("/configissues/").data

    (app_dir / "secrets" / "secret_app.env").write_text("SECRET_KEY=" + "z" * 32)
    assert client.get("/x").data == b"ok"
