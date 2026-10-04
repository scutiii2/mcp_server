import json
import shutil
from pathlib import Path

from dotenv import dotenv_values

from src.utils.catalog import catalog


@catalog
def load_json_config(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        example = path.with_name(path.name + ".example")
        if not example.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        shutil.copyfile(example, path)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@catalog
def load_env_secrets(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        example = path.with_name(path.name + ".example")
        if not example.exists():
            return {}
        shutil.copyfile(example, path)
    return dict(dotenv_values(path))


@catalog
def load_all_json_configs(configs_dir: str | Path) -> dict[str, dict]:
    configs_dir = Path(configs_dir)
    if not configs_dir.exists():
        return {}
    for example in configs_dir.glob("*.json.example"):
        target = example.with_suffix("")
        if not target.exists():
            shutil.copyfile(example, target)
    return {file.stem: load_json_config(file) for file in sorted(configs_dir.glob("*.json"))}
