from __future__ import annotations

import json
from pathlib import Path

from src.config import MB, Limits, load_settings

EXAMPLE = Path(__file__).resolve().parent.parent / "configs" / "config_pdf_merger.json.example"


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    configs, secrets_dir = tmp_path / "configs", tmp_path / ".secrets"
    configs.mkdir()
    secrets_dir.mkdir()
    (configs / "config_pdf_merger.json.example").write_text(EXAMPLE.read_text("utf-8"), "utf-8")
    return configs, secrets_dir


def test_missing_config_is_copied_from_example(tmp_path: Path):
    configs, secrets_dir = _dirs(tmp_path)

    settings = load_settings(configs, secrets_dir, env={})

    assert (configs / "config_pdf_merger.json").exists()
    assert settings.port == 8040
    assert settings.public_base_url == "http://127.0.0.1:8040"
    assert settings.limits == Limits()
    assert settings.file_ttl_seconds == 6 * 3600


def test_env_overrides_port_and_public_url_follows(tmp_path: Path):
    configs, secrets_dir = _dirs(tmp_path)

    settings = load_settings(configs, secrets_dir, env={"PDF_MERGER_PORT": "9999"})

    assert settings.port == 9999
    assert settings.public_base_url == "http://127.0.0.1:9999"


def test_limits_are_read_in_friendly_units(tmp_path: Path):
    configs, secrets_dir = _dirs(tmp_path)
    raw = json.loads(EXAMPLE.read_text("utf-8"))
    raw["limits"]["max_file_mb"] = 5
    raw["limits"]["max_image_megapixels"] = 1.5
    (configs / "config_pdf_merger.json").write_text(json.dumps(raw), "utf-8")

    settings = load_settings(configs, secrets_dir, env={})

    assert settings.limits.max_file_bytes == 5 * MB
    assert settings.limits.max_image_pixels == 1_500_000


def test_secrets_are_read_from_env_files(tmp_path: Path):
    configs, secrets_dir = _dirs(tmp_path)
    (secrets_dir / "secret_internal_api.env").write_text("INTERNAL_API_TOKEN=abc\n", "utf-8")
    (secrets_dir / "secret_signing.env").write_text("PDF_MERGER_SIGNING_KEY=key\n", "utf-8")

    settings = load_settings(configs, secrets_dir, env={})

    assert settings.internal_api_token == "abc"
    assert settings.signing_key == b"key"


def test_missing_signing_key_gets_a_random_one(tmp_path: Path):
    configs, secrets_dir = _dirs(tmp_path)

    first = load_settings(configs, secrets_dir, env={})
    second = load_settings(configs, secrets_dir, env={})

    assert len(first.signing_key) == 64
    assert first.signing_key != second.signing_key
