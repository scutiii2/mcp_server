"""Tests for infra/app_config.py - the loader for chat_app's own
config.json (currently just the Ollama desired-model list).

Mirrors the shape of mcp_server's own test_app_config.py: mostly about
the *failure* messages, since a loader that silently swallows a
malformed entry is exactly what this project avoids.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.services.llm.app_config import load_ollama_models
from src.services.llm.base import ModelOption


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_missing_config_file_returns_empty_list(tmp_path: Path):
    """No config.json at all - every install that predates this feature -
    must not need one just to start without Ollama."""
    missing = tmp_path / "does-not-exist.json"

    assert load_ollama_models(missing) == []


def test_missing_providers_section_returns_empty_list(tmp_path: Path):
    path = _write(tmp_path, {})

    assert load_ollama_models(path) == []


def test_missing_ollama_section_returns_empty_list(tmp_path: Path):
    path = _write(tmp_path, {"providers": {}})

    assert load_ollama_models(path) == []


def test_missing_models_key_returns_empty_list(tmp_path: Path):
    """"providers.ollama" present but without "models" is a deployment
    that configured the section but listed nothing - empty, not an
    error."""
    path = _write(tmp_path, {"providers": {"ollama": {}}})

    assert load_ollama_models(path) == []


def test_valid_config_parses_into_model_options(tmp_path: Path):
    path = _write(
        tmp_path,
        {
            "providers": {
                "ollama": {
                    "models": [
                        {"id": "qwen2.5:7b", "label": "Qwen 2.5 7B (local)"},
                        {"id": "llama3.2:1b", "label": "Llama 3.2 1B (local)"},
                    ]
                }
            }
        },
    )

    models = load_ollama_models(path)

    assert models == [
        ModelOption(id="qwen2.5:7b", label="Qwen 2.5 7B (local)"),
        ModelOption(id="llama3.2:1b", label="Llama 3.2 1B (local)"),
    ]


def test_entry_missing_id_fails_loudly_naming_the_index(tmp_path: Path):
    path = _write(tmp_path, {"providers": {"ollama": {"models": [{"label": "No id"}]}}})

    with pytest.raises(KeyError, match=r"models\[0\].*'id'"):
        load_ollama_models(path)


def test_entry_missing_label_fails_loudly_naming_the_index(tmp_path: Path):
    path = _write(tmp_path, {"providers": {"ollama": {"models": [{"id": "qwen2.5:7b"}]}}})

    with pytest.raises(KeyError, match=r"models\[0\].*'label'"):
        load_ollama_models(path)


def test_entry_with_non_string_id_fails_loudly(tmp_path: Path):
    path = _write(tmp_path, {"providers": {"ollama": {"models": [{"id": 123, "label": "Bad id type"}]}}})

    with pytest.raises(ValueError, match=r"models\[0\].id"):
        load_ollama_models(path)


def test_entry_with_non_string_label_fails_loudly(tmp_path: Path):
    path = _write(tmp_path, {"providers": {"ollama": {"models": [{"id": "qwen2.5:7b", "label": 123}]}}})

    with pytest.raises(ValueError, match=r"models\[0\].label"):
        load_ollama_models(path)


def test_recursive_chain_defaults_to_false_when_absent(tmp_path: Path):
    """Existing config.json files (and every model entry that predates
    this field) shouldn't need it just to keep loading."""
    path = _write(
        tmp_path,
        {"providers": {"ollama": {"models": [{"id": "qwen2.5:7b", "label": "Qwen"}]}}},
    )

    models = load_ollama_models(path)

    assert models == [ModelOption(id="qwen2.5:7b", label="Qwen", recursive_chain=False)]


def test_recursive_chain_true_parses_into_model_options(tmp_path: Path):
    path = _write(
        tmp_path,
        {
            "providers": {
                "ollama": {
                    "models": [
                        {"id": "phi4-mini:latest", "label": "Phi 4 Mini", "recursive_chain": True},
                    ]
                }
            }
        },
    )

    models = load_ollama_models(path)

    assert models == [ModelOption(id="phi4-mini:latest", label="Phi 4 Mini", recursive_chain=True)]


def test_entry_with_non_bool_recursive_chain_fails_loudly(tmp_path: Path):
    path = _write(
        tmp_path,
        {
            "providers": {
                "ollama": {
                    "models": [{"id": "qwen2.5:7b", "label": "Qwen", "recursive_chain": "yes"}]
                }
            }
        },
    )

    with pytest.raises(ValueError, match=r"models\[0\].recursive_chain"):
        load_ollama_models(path)


def test_non_object_entry_fails_loudly(tmp_path: Path):
    path = _write(tmp_path, {"providers": {"ollama": {"models": ["qwen2.5:7b"]}}})

    with pytest.raises(ValueError, match=r"models\[0\]"):
        load_ollama_models(path)


def test_models_key_not_a_list_fails_loudly(tmp_path: Path):
    path = _write(tmp_path, {"providers": {"ollama": {"models": "qwen2.5:7b"}}})

    with pytest.raises(ValueError, match="providers.ollama.models"):
        load_ollama_models(path)


def test_providers_section_not_an_object_fails_loudly(tmp_path: Path):
    path = _write(tmp_path, {"providers": ["not", "an", "object"]})

    with pytest.raises(ValueError, match="'providers'"):
        load_ollama_models(path)


def test_ollama_section_not_an_object_fails_loudly(tmp_path: Path):
    path = _write(tmp_path, {"providers": {"ollama": ["not", "an", "object"]}})

    with pytest.raises(ValueError, match="providers.ollama"):
        load_ollama_models(path)


def test_malformed_json_fails_loudly(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid JSON"):
        load_ollama_models(path)


def test_staged_pipeline_defaults_to_false_when_absent(tmp_path: Path):
    path = _write(
        tmp_path,
        {"providers": {"ollama": {"models": [{"id": "qwen2.5:7b", "label": "Qwen"}]}}},
    )

    models = load_ollama_models(path)

    assert models == [ModelOption(id="qwen2.5:7b", label="Qwen", staged_pipeline=False)]


def test_staged_pipeline_true_parses_into_model_options(tmp_path: Path):
    path = _write(
        tmp_path,
        {
            "providers": {
                "ollama": {
                    "models": [{"id": "phi4-mini:latest", "label": "Phi 4 Mini", "staged_pipeline": True}]
                }
            }
        },
    )

    models = load_ollama_models(path)

    assert models == [ModelOption(id="phi4-mini:latest", label="Phi 4 Mini", staged_pipeline=True)]


def test_entry_with_non_bool_staged_pipeline_fails_loudly(tmp_path: Path):
    path = _write(
        tmp_path,
        {"providers": {"ollama": {"models": [{"id": "qwen2.5:7b", "label": "Qwen", "staged_pipeline": "yes"}]}}},
    )

    with pytest.raises(ValueError, match=r"models\[0\].staged_pipeline"):
        load_ollama_models(path)


def test_recursive_chain_and_staged_pipeline_both_true_fails_loudly(tmp_path: Path):
    path = _write(
        tmp_path,
        {
            "providers": {
                "ollama": {
                    "models": [
                        {
                            "id": "phi4-mini:latest",
                            "label": "Phi 4 Mini",
                            "recursive_chain": True,
                            "staged_pipeline": True,
                        }
                    ]
                }
            }
        },
    )

    with pytest.raises(ValueError, match="mutually exclusive"):
        load_ollama_models(path)
