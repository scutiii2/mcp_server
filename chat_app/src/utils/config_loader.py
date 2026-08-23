import json
from pathlib import Path

from dotenv import dotenv_values


def load_json_config(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_env_secrets(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    return dict(dotenv_values(path))


def load_all_json_configs(configs_dir: str | Path) -> dict[str, dict]:
    configs_dir = Path(configs_dir)
    if not configs_dir.exists():
        return {}
    return {file.stem: load_json_config(file) for file in sorted(configs_dir.glob("*.json"))}
