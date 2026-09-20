"""Auto-create a missing config/secret file from its `.example` sibling."""

import shutil
from pathlib import Path


def seed_from_example(path: Path) -> None:
    if path.exists():
        return
    example = path.with_name(path.name + ".example")
    if example.exists():
        shutil.copyfile(example, path)
