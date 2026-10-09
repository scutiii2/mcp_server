"""First-read migration and shared consumers for ai_agent's tuning config."""

import json
from pathlib import Path

import pytest

from src.core import config_files
from src.llm import token_limits


@pytest.fixture
def tuning_path(tmp_path):
    path = tmp_path / "config_tuning.json"
    examples = Path(config_files.__file__).resolve().parents[2] / "configs"
    path.with_suffix(".json.example").write_bytes(
        (examples / "config_tuning.json.example").read_bytes()
    )
    return path


def test_fresh_install_seeds_token_limits(tuning_path):
    limits = config_files.read_section(tuning_path, "token_limits")
    assert limits["default"]["max_tool_rounds"] == 15
    assert json.loads(tuning_path.read_text(encoding="utf-8")).keys() == {"token_limits"}


def test_migration_preserves_legacy_limits_and_file(tuning_path):
    legacy = {"token_limits": {"default": {"max_output_tokens": 987, "max_context_tokens": 12345,
                                           "max_tool_rounds": 9},
                               "openai": {"gateways": {"ollama": {"max_context_tokens": 4321}}}}}
    old_path = tuning_path.parent / "config_limits.json"
    old_path.write_text(json.dumps(legacy), encoding="utf-8")
    original = old_path.read_bytes()

    config_files.read_section(tuning_path, "token_limits")
    merged = json.loads(tuning_path.read_text(encoding="utf-8"))
    defaults = json.loads(tuning_path.with_suffix(".json.example").read_text(encoding="utf-8"))
    assert merged == {**defaults, **legacy}
    assert old_path.read_bytes() == original
    assert not list(tuning_path.parent.glob("*.tmp"))


def test_existing_tuning_wins_and_is_not_rewritten(tuning_path):
    content = '{"token_limits": {"default": {}}}\n'
    tuning_path.write_text(content, encoding="utf-8")
    (tuning_path.parent / "config_limits.json").write_text("broken", encoding="utf-8")
    assert config_files.read_section(tuning_path, "token_limits") == {"default": {}}
    assert tuning_path.read_text(encoding="utf-8") == content


@pytest.mark.parametrize("bad", ['{broken', '[]', '{}'])
def test_invalid_legacy_limits_do_not_create_tuning(tuning_path, bad):
    (tuning_path.parent / "config_limits.json").write_text(bad, encoding="utf-8")
    with pytest.raises(ValueError):
        config_files.read_section(tuning_path, "token_limits")
    assert not tuning_path.exists()


def test_token_limits_read_the_shared_tuning_file(tuning_path, monkeypatch):
    assert token_limits._CONFIG_PATH == config_files.TUNING_PATH
    data = {"token_limits": {"default": {"max_output_tokens": 101, "max_context_tokens": 202,
                                        "max_tool_rounds": 3}}}
    tuning_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(token_limits, "_CONFIG_PATH", tuning_path)
    token_limits.reset_cache()
    try:
        assert token_limits.max_output_tokens("anthropic") == 101
    finally:
        token_limits.reset_cache()
