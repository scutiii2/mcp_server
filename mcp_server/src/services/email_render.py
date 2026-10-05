"""Renders the body templates in ``email_templates/`` for ``send_email()``.

Templates are plain ``string.Template`` files so a message's wording can be
changed without touching Python. Values are HTML-escaped by default, since
they usually carry names or text a user typed; a name ending in ``_html``
opts out for markup the caller built itself.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from string import Template

from src.utils.catalog import catalog

TEMPLATE_DIR = Path(__file__).parent / "email_templates"

_RAW_SUFFIX = "_html"


def available_templates() -> list[str]:
    """Names accepted by ``render_email_template``."""
    return sorted(path.stem for path in TEMPLATE_DIR.glob("*.html"))


@catalog
def render_email_template(name: str, **values: str) -> str:
    """Fill ``email_templates/<name>.html`` and return the HTML body.

    Raises ``ValueError`` for an unknown template (or a name that tries to
    leave the folder) and ``KeyError`` for a placeholder with no value.
    """
    if name not in available_templates():
        raise ValueError(f"Unknown email template {name!r}; expected one of {available_templates()}.")
    source = (TEMPLATE_DIR / f"{name}.html").read_text(encoding="utf-8")
    safe = {
        key: value if key.endswith(_RAW_SUFFIX) else escape(str(value))
        for key, value in values.items()
    }
    return Template(source).substitute(safe).strip()
