"""Colors, sizes and small color/easing helpers shared by the widgets and window."""

from __future__ import annotations


_SIDEBAR_WIDTH = 220

# Corner radius scale, same steps as ember_web's --radius-* tokens: radius follows element size.
_RADIUS_SM = 4   # chip, badge
_RADIUS_MD = 8   # button, row
_RADIUS_LG = 12  # card, panel
_RADIUS = _RADIUS_MD

# Colors are ember_web's dark tokens (apps/Ember/ember_web/src/style.css); the launcher is dark only.
_BG = "#17171a"              # --bg
_SIDEBAR_BG = "#1f1f23"      # --surface
_TABBAR_BG = "#1f1f23"
_ROW_BG = "#1f1f23"          # unselected button/card fill
_ROW_SELECTED = "#2a2a30"    # --user-bubble
_FIELD_BG = "#232328"        # --code-bg
_BORDER = "#2f2f35"          # --border
_FG = "#e8e8ea"              # --text
_DIM_FG = "#9a9aa3"          # --muted
_SEPARATOR = "#2f2f35"
_ACCENT = "#ff7a33"          # --accent, ember orange: one primary action per view
_ACCENT_CONTRAST = "#17171a"
_DANGER = "#ff8a4c"          # --danger, text on dark surfaces
_DANGER_BORDER = "#5a3a2a"
_GREEN = "#199e70"           # --success
_RED = "#d03b3b"             # --status-failed
_ORANGE = "#f0b429"          # --warning
# Status badges are quiet tints with colored text, so color is never the only cue (the label is shown too).
_STATUS_FILLS = {
    "running": "#173a31",
    "failed": "#3d1f21",
    "stopping": "#3d3220",
}
_STATUS_FGS = {
    "running": "#3ccf9a",
    "failed": "#ff7b7b",
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
_ERROR_FG = "#ff7b7b"  # readable red text on _BG
_HOVER_DURATION_MS = 180
