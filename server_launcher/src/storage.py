"""JSON persistence for saved groups, presets and the kept-running handoff file."""

from __future__ import annotations

import json

from .config import _GROUPS_PATH, _KEPT_RUNNING_PATH, _PRESETS_PATH
from .models import GroupMember, Preset, ServerGroup


def _load_groups() -> dict[str, ServerGroup]:
    if not _GROUPS_PATH.exists():
        return {}
    try:
        raw = json.loads(_GROUPS_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError
        groups = {
            name: ServerGroup(
                name,
                [
                    GroupMember(
                        member["template_key"],
                        member["port"],
                        member.get("extra_env", {}),
                        member.get("extra_args", ""),
                        member.get("preset_name"),
                    )
                    for member in group["members"]
                ],
            )
            for name, group in raw.items()
        }
        for name, group in groups.items():
            if not isinstance(name, str) or not isinstance(raw[name], dict) or not isinstance(raw[name]["members"], list):
                raise TypeError
            for member in group.members:
                if (
                    not isinstance(member.template_key, str)
                    or not isinstance(member.port, int) or isinstance(member.port, bool)
                    or not 1 <= member.port <= 65535
                    or not isinstance(member.extra_env, dict)
                    or not all(isinstance(key, str) and isinstance(value, str) for key, value in member.extra_env.items())
                    or not isinstance(member.extra_args, str)
                    or member.preset_name is not None and not isinstance(member.preset_name, str)
                ):
                    raise TypeError
        return groups
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, AttributeError):
        return {}


def _save_groups(groups: dict[str, ServerGroup]) -> None:
    _GROUPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = {
        name: {
            "members": [
                {
                    "template_key": member.template_key,
                    "port": member.port,
                    "extra_env": member.extra_env,
                    "extra_args": member.extra_args,
                    "preset_name": member.preset_name,
                }
                for member in group.members
            ]
        }
        for name, group in groups.items()
    }
    _GROUPS_PATH.write_text(json.dumps(raw, indent=2), encoding="utf-8")


def _load_presets() -> dict[str, list[Preset]]:
    if not _PRESETS_PATH.exists():
        return {}
    try:
        raw = json.loads(_PRESETS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    presets: dict[str, list[Preset]] = {}
    for template_key, entries in raw.items():
        presets[template_key] = [
            Preset(e["name"], e["port"], e.get("env_vars", {}), e.get("args", "")) for e in entries
        ]
    return presets


def _save_presets(presets: dict[str, list[Preset]]) -> None:
    _PRESETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = {
        template_key: [{"name": p.name, "port": p.port, "env_vars": p.env_vars, "args": p.args} for p in entries]
        for template_key, entries in presets.items()
    }
    _PRESETS_PATH.write_text(json.dumps(raw, indent=2), encoding="utf-8")


def _load_and_clear_kept_running() -> list[tuple[str, int]]:
    """Reads then immediately deletes the file - one-shot, so a crash or a
    manually-deleted instance later doesn't leave a stale entry behind for
    every future launch to keep trying to re-adopt."""
    if not _KEPT_RUNNING_PATH.exists():
        return []
    try:
        raw = json.loads(_KEPT_RUNNING_PATH.read_text(encoding="utf-8"))
        entries = [(e["template_key"], e["port"]) for e in raw]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        entries = []
    _KEPT_RUNNING_PATH.unlink(missing_ok=True)
    return entries


def _save_kept_running(entries: list[tuple[str, int]]) -> None:
    _KEPT_RUNNING_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = [{"template_key": key, "port": port} for key, port in entries]
    _KEPT_RUNNING_PATH.write_text(json.dumps(raw, indent=2), encoding="utf-8")
