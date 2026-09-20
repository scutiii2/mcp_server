"""Context-window sizes for the usage bar (see server.py's status()/ask()
and agent_config.py's status()). AI_AGENT_MODEL is a free-form env var -
any string the configured provider accepts - so this can't be an
exhaustive enum; CONTEXT_WINDOWS is matched by substring against known
model-name prefixes, with a conservative fallback for anything unlisted
so an unrecognized model string still renders a usable bar instead of
crashing or showing nothing.
"""

from __future__ import annotations

from src.catalog import catalog

CONTEXT_WINDOWS: dict[str, int] = {
    "claude": 200_000,
    "gpt-5": 400_000,
    "gpt-4.1": 1_000_000,
    "gpt-4": 128_000,
    "o1": 200_000,
    "o3": 200_000,
    "minicpm": 16_384,
}

DEFAULT_CONTEXT_WINDOW = 128_000


@catalog
def context_window_for(model: str | None) -> int:
    if model:
        lowered = model.lower()
        for prefix, window in CONTEXT_WINDOWS.items():
            if prefix in lowered:
                return window
    return DEFAULT_CONTEXT_WINDOW
