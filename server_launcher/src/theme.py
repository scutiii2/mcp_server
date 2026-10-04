"""Colors, sizes and small color/easing helpers shared by the widgets and window."""

from __future__ import annotations


_SIDEBAR_WIDTH = 220
_RADIUS = 8

_BG = "#1c1c21"
_SIDEBAR_BG = "#1c1c21"
_ROW_BG = "#1c1c21"          # unselected button/card bg - same as main bg, outline-only look
_ROW_SELECTED = "#5b5c62"
_FIELD_BG = "#1c1c21"
_BORDER = "#6a6b70"          # button outline
_FG = "#f5f5f7"               # primary text/icons - brightened, #66707a was unreadable on #1c1c21
_DIM_FG = "#a0a3a8"           # secondary text - also brightened for the same reason
_SEPARATOR = "#66707a"
_GREEN = "#12562a"
_RED = "#720714"
_ORANGE = "#7a4212"
_STATUS_FILLS = {
    "running": _GREEN,
    "failed": _RED,
    "stopping": _ORANGE,
}


def _lighten(hex_color: str, amount: float) -> str:
    """amount in [0, 1]: 0 leaves the color unchanged, 1 is white."""
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    r = round(r + (255 - r) * amount)
    g = round(g + (255 - g) * amount)
    b = round(b + (255 - b) * amount)
    return f"#{r:02x}{g:02x}{b:02x}"


def _ease_in_out(t: float) -> float:
    """Smoothstep - eases in from 0 and back out approaching 1, no linear
    snap at either end. Used for the hover sheen's fade in/out."""
    return t * t * (3 - 2 * t)


_HOVER_LIGHTEN = 0.22
_HOVER_DURATION_MS = 180
