"""Loads gateways/<provider>/<gateway>.json base_url/model presets.

Real secrets never live in that file: any "{ENV_VAR_NAME}" string value is
a pointer, resolved here against the process environment (populated from
.env by agent_config.py's _load_secrets_into_environ) - never
taken literally. A gateway block with an unresolved placeholder just
yields None for that key, same as the var being blank in .env.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.agents.agent_spec import TIERS
from src.core.catalog import catalog

_ROOT = Path(__file__).resolve().parent.parent.parent
GATEWAYS_DIR = _ROOT / "gateways"
_LEGACY_PATH = _ROOT / "configs" / "config_gateways.json"
_PLACEHOLDER = re.compile(r"^\{([A-Z0-9_]+)\}$")
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

_config: dict[str, Any] | None = None


@catalog
def load_gateways() -> dict[str, Any]:
    """Raw gateway blocks grouped by provider, cached until process restart.

    First read migrates legacy settings. Existing
    individual files win; the legacy file remains an unused rollback backup.
    """
    global _config
    if _config is None:
        _initialize()
        found: dict[str, Any] = {}
        for path in sorted(GATEWAYS_DIR.glob("*/*.json")):
            provider, name = path.parent.name, path.stem
            if not _NAME.fullmatch(provider) or not _NAME.fullmatch(name):
                raise ValueError(f"{path}: invalid provider or gateway name")
            found.setdefault(provider, {})[name] = _read_block(path)
        _config = found
    return _config


def _read_block(path: Path) -> dict[str, Any]:
    try:
        block = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ValueError(f"{path}: invalid JSON") from error
    if not isinstance(block, dict):
        raise ValueError(f"{path}: must be an object")
    return block


def _initialize() -> None:
    marker = GATEWAYS_DIR / ".initialized"
    if marker.exists():
        return
    pending: dict[Path, dict[str, Any]] = {}
    if _LEGACY_PATH.exists():
        legacy = _read_block(_LEGACY_PATH)
        # Validate the complete legacy file before publishing any migration.
        for provider, gateways in legacy.items():
            if not _NAME.fullmatch(provider) or not isinstance(gateways, dict):
                raise ValueError(f"{_LEGACY_PATH}: invalid provider {provider!r}")
            for name, block in gateways.items():
                if not _NAME.fullmatch(name) or not isinstance(block, dict):
                    raise ValueError(f"{_LEGACY_PATH}: invalid gateway {provider}.{name}")
                pending[GATEWAYS_DIR / provider / f"{name}.json"] = block
    for path, block in pending.items():
        _publish_missing(path, json.dumps(block, indent=2) + "\n")
    # Mark only a completed initialization, so interrupted migrations can retry.
    _publish_missing(marker, "Gateway initialization complete. Legacy config is no longer read.\n")


def _publish_missing(path: Path, content: str) -> None:
    """Publish a complete file without overwriting local edits or parallel starts."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
        try:
            if os.name == "nt":
                # Windows rename is atomic and refuses an existing destination.
                os.rename(temporary, path)
            else:
                os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _resolve(value: Any) -> Any:
    if isinstance(value, str):
        match = _PLACEHOLDER.match(value)
        if match:
            return os.getenv(match.group(1)) or None
    return value


@catalog
def gateway(provider: str, gateway_name: str) -> dict[str, Any]:
    """One gateway's config block, e.g. gateway("anthropic", "openrouter")
    - {ENV_VAR} placeholders resolved to their live env var value (None if
    that var is unset). Raises KeyError if provider/gateway_name isn't in
    gateways/."""
    block = load_gateways()[provider][gateway_name]
    return {key: _resolve(value) for key, value in block.items()}


@dataclass(frozen=True)
class TierModel:
    """One model a gateway offers for a strength tier."""

    id: str
    use_for: str


def _text(entry: dict[str, Any], key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}.{key} must be a non-empty string")
    return value.strip()


@catalog
def tiers(provider: str, gateway_name: str) -> dict[str, TierModel]:
    """The strength tiers one gateway offers, e.g. tiers("anthropic",
    "claude") - {"light": TierModel(...), ...} in ladder order (light,
    standard, heavy), from the block's optional `models` map. A tier whose
    `id` is an {ENV_VAR} placeholder that is unset is left out. Returns {}
    when the block has no `models`. Raises KeyError if provider/gateway_name
    isn't in gateways/ and ValueError for a malformed `models`."""
    models = load_gateways()[provider][gateway_name].get("models")
    if models is None:
        return {}
    where = f"gateways/{provider}/{gateway_name}.json {provider}.{gateway_name}.models"
    if not isinstance(models, dict):
        raise ValueError(f"{where} must be an object")
    for name in models:
        if name not in TIERS:
            raise ValueError(f"{where}.{name} is not a tier (use: {', '.join(TIERS)})")
    found: dict[str, TierModel] = {}
    for name in TIERS:
        if name not in models:
            continue
        entry = models[name]
        if not isinstance(entry, dict):
            raise ValueError(f"{where}.{name} must be an object")
        use_for = _text(entry, "use_for", f"{where}.{name}")
        model_id = _resolve(_text(entry, "id", f"{where}.{name}"))
        if model_id:
            found[name] = TierModel(model_id, use_for)
    return found
