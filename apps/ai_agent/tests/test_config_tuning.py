"""First-read migration and shared consumers for ai_agent's tuning config."""

import json
from pathlib import Path

import pytest

from src.core import config_files
from src.llm import token_limits
from src.mcp_client import tool_selection


@pytest.fixture
def tuning_path(tmp_path):
    path = tmp_path / "config_tuning.json"
    examples = Path(config_files.__file__).resolve().parents[2] / "configs"
    path.with_suffix(".json.example").write_bytes(
        (examples / "config_tuning.json.example").read_bytes()
    )
    return path


def test_fresh_install_seeds_both_sections(tuning_path):
    limits = config_files.read_section(tuning_path, "token_limits")
    selection = config_files.read_section(tuning_path, "tool_selection")
    assert limits["default"]["max_tool_rounds"] == 15
    assert selection == {"enabled": False, "top_k": 20}


@pytest.mark.parametrize("legacy_sections", [
    {"token_limits": {"default": {"max_output_tokens": 987, "max_context_tokens": 12345,
                                  "max_tool_rounds": 9},
                      "openai": {"gateways": {"ollama": {"max_context_tokens": 4321}}}}},
    {"tool_selection": {"enabled": True, "top_k": 7}},
    {"token_limits": {"default": {"max_output_tokens": 987, "max_context_tokens": 12345,
                                  "max_tool_rounds": 9}},
     "tool_selection": {"enabled": True, "top_k": 7}},
])
def test_migration_preserves_legacy_values_and_files(tuning_path, legacy_sections):
    old_names = {"token_limits": "config_limits.json",
                 "tool_selection": "config_tool_selection.json"}
    originals = {}
    for section, value in legacy_sections.items():
        old_path = tuning_path.parent / old_names[section]
        old_path.write_text(json.dumps({section: value}), encoding="utf-8")
        originals[old_path] = old_path.read_bytes()

    config_files.read_section(tuning_path, "token_limits")
    merged = json.loads(tuning_path.read_text(encoding="utf-8"))
    defaults = json.loads(tuning_path.with_suffix(".json.example").read_text(encoding="utf-8"))
    assert merged == {**defaults, **legacy_sections}
    assert all(path.read_bytes() == original for path, original in originals.items())
    assert not list(tuning_path.parent.glob("*.tmp"))


def test_existing_tuning_wins_and_is_not_rewritten(tuning_path):
    content = '{"token_limits": {"default": {}}, "tool_selection": {"top_k": 3}}\n'
    tuning_path.write_text(content, encoding="utf-8")
    (tuning_path.parent / "config_limits.json").write_text("broken", encoding="utf-8")
    assert config_files.read_section(tuning_path, "tool_selection") == {"top_k": 3}
    assert tuning_path.read_text(encoding="utf-8") == content


@pytest.mark.parametrize("bad", ['{broken', '[]', '{}'])
def test_invalid_legacy_limits_do_not_create_tuning(tuning_path, bad):
    (tuning_path.parent / "config_limits.json").write_text(bad, encoding="utf-8")
    with pytest.raises(ValueError):
        config_files.read_section(tuning_path, "token_limits")
    assert not tuning_path.exists()


def test_both_consumers_read_the_same_file(tuning_path, monkeypatch):
    assert token_limits._CONFIG_PATH == tool_selection._CONFIG_PATH == config_files.TUNING_PATH
    data = {"token_limits": {"default": {"max_output_tokens": 101, "max_context_tokens": 202,
                                        "max_tool_rounds": 3}},
            "tool_selection": {"enabled": True, "top_k": 4}}
    tuning_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(token_limits, "_CONFIG_PATH", tuning_path)
    monkeypatch.setattr(tool_selection, "_CONFIG_PATH", tuning_path)
    token_limits.reset_cache()
    tool_selection.reset_cache()
    try:
        assert token_limits.max_output_tokens("anthropic") == 101
        assert tool_selection.is_enabled() is True
        assert tool_selection.top_k() == 4
    finally:
        token_limits.reset_cache()
        tool_selection.reset_cache()
