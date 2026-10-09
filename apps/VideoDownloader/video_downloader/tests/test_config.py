from __future__ import annotations

import json
from pathlib import Path

from src.config import MB, load_settings


def _dirs(tmp_path: Path, raw: dict | None = None) -> tuple[Path, Path]:
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "config_video_downloader.json").write_text(json.dumps(raw or {}), "utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("", "utf-8")
    return configs, env_file


def test_defaults(tmp_path):
    configs, env_file = _dirs(tmp_path)
    settings = load_settings(configs, env_file, env={})
    assert settings.port == 8050
    assert settings.public_base_url == "http://127.0.0.1:8050"
    assert settings.web_origin == "http://127.0.0.1:5175"
    assert settings.limits.max_file_bytes == 500 * MB
    assert settings.limits.max_duration_seconds == 7200
    assert settings.limits.max_session_bytes == 2048 * MB
    assert settings.limits.max_concurrent_downloads == 2
    assert settings.file_ttl_seconds == 6 * 3600
    assert settings.download_link_seconds == 3600
    assert settings.internal_api_token == ""
    assert len(settings.signing_key) > 0  # random per process when unset


def test_env_overrides(tmp_path):
    configs, env_file = _dirs(tmp_path)
    env = {
        "VIDEO_DOWNLOADER_PORT": "9000",
        "VIDEO_DOWNLOADER_WEB_PORT": "9001",
        "INTERNAL_API_TOKEN": "tok",
        "VIDEO_DOWNLOADER_SIGNING_KEY": "key",
        "VIDEO_DOWNLOADER_PUBLIC_BASE_URL": "http://10.0.0.5:9000/",
    }
    settings = load_settings(configs, env_file, env=env)
    assert settings.port == 9000
    assert settings.web_origin == "http://127.0.0.1:9001"
    assert settings.public_base_url == "http://10.0.0.5:9000"
    assert settings.internal_api_token == "tok"
    assert settings.signing_key == b"key"


def test_config_file_overrides_limits(tmp_path):
    configs, env_file = _dirs(tmp_path, {"file_ttl_hours": 1, "limits": {"max_file_mb": 10, "max_duration_minutes": 5, "job_timeout_minutes": 2}})
    settings = load_settings(configs, env_file, env={})
    assert settings.file_ttl_seconds == 3600
    assert settings.limits.max_file_bytes == 10 * MB
    assert settings.limits.max_duration_seconds == 300
    assert settings.limits.job_timeout_seconds == 120


def test_missing_config_is_copied_from_example(tmp_path):
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "config_video_downloader.json.example").write_text("{}", "utf-8")
    env_file = tmp_path / ".env"
    (tmp_path / ".env.example").write_text("VIDEO_DOWNLOADER_PORT=8123\n", "utf-8")
    settings = load_settings(configs, env_file, env=None)
    assert (configs / "config_video_downloader.json").exists()
    assert env_file.exists()
    assert settings.port in (8123, 8050)  # real os.environ may override
