"""Loader for chat_app's own JSON config file.

Currently holds one thing - the Ollama desired-model list - but the shape
(``providers.<id>.*``) is deliberately extensible for other providers
later without a rewrite.

Deliberately smaller than mcp_server's ``infra/app_config.py``: nothing
here is a secret (model ids/labels aren't sensitive), so there's no
``${VAR}`` environment-substitution machinery to carry over. If a future
section here does need that, treat
``mcp_server/src/mcp_server/infra/app_config.py`` as the reference
implementation to mirror rather than growing one here independently.

Same fail-loudly convention as the rest of this project: ``KeyError`` for
something required and absent, ``ValueError`` for present-but-malformed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chat_app.services.llm.base import ModelOption


def load_config(config_path: Path) -> dict[str, Any]:
    """Read and parse the config file. Raises on anything unusable."""
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}. Copy config.json.example "
            f"and point CHAT_CONFIG_PATH at it."
        )
    try:
        with config_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as error:
        raise ValueError(f"Config file {config_path} is not valid JSON: {error}") from error

    if not isinstance(data, dict):
        raise ValueError(f"Config file {config_path} must contain a JSON object at the top level")
    return data


def load_ollama_models(config_path: Path) -> list[ModelOption]:
    """Parse "providers.ollama.models" into ``ModelOption``s.

    No config file at all, a missing "providers" key, or a missing
    "providers.ollama" key are all treated the same way - an empty list,
    not an error. A deployment that doesn't use Ollama (including every
    install that predates this feature and has no config.json yet)
    shouldn't need this section, or the file, just to start.

    A PRESENT "providers.ollama.models" entry that's malformed (missing
    "id"/"label", wrong types) fails loudly instead, naming exactly what's
    wrong - silently dropping a bad entry would mean a typo in config.json
    quietly shrinks the model list instead of surfacing at startup.
    """
    if not config_path.exists():
        return []

    config = load_config(config_path)
    providers = config.get("providers")
    if providers is None:
        return []
    if not isinstance(providers, dict):
        raise ValueError(f"Config file {config_path}: 'providers' must be an object")

    ollama = providers.get("ollama")
    if ollama is None:
        return []
    if not isinstance(ollama, dict):
        raise ValueError(f"Config file {config_path}: 'providers.ollama' must be an object")

    raw_models = ollama.get("models", [])
    if not isinstance(raw_models, list):
        raise ValueError(f"Config file {config_path}: 'providers.ollama.models' must be a list")

    models: list[ModelOption] = []
    for index, entry in enumerate(raw_models):
        where = f"providers.ollama.models[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"Config file {config_path}: '{where}' must be an object")

        if "id" not in entry:
            raise KeyError(f"Config file {config_path}: '{where}' is missing 'id'")
        if "label" not in entry:
            raise KeyError(f"Config file {config_path}: '{where}' is missing 'label'")

        model_id = entry["id"]
        label = entry["label"]
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError(f"Config file {config_path}: '{where}.id' must be a non-empty string")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"Config file {config_path}: '{where}.label' must be a non-empty string")

        models.append(ModelOption(id=model_id, label=label))

    return models
