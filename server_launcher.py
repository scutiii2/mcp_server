"""Desktop launcher for this repo's dev servers.

Autodetects every `<project>/run.bat` (mcp_server/run.bat, chat_app/
run.bat, catalog_service/run.bat, ai_agent/run.bat - parsing each one's
venv-folder and `py -m <module>` lines, see discover_templates()) and
runs each one directly as `<project>/.venv_<id>/Scripts/python.exe -m
<module>`, bypassing the bat's own activate/bootstrap/restart-prompt
wrapper. That's not just a style choice: running the interpreter this
way gives a real Popen handle with piped stdout, which is what makes an
in-app log viewer and a programmatic stop/restart possible - going
through `start ... cmd /k` (as this tool's first version did) hands the
process off to a detached console window this tool can never read from
or reliably kill.

Each project's `.venv_<id>` lives inside that project's own folder, and
if it doesn't exist yet, this tool bootstraps it itself the same way the
bat would (`py -m venv .venv_<id>` then `pip install -e .[dev]`),
streaming that output into the instance's own log the same as the
server's - see Instance._boot_and_run(). The bats keep an identical
bootstrap block for anyone running them directly instead of through this
tool.

Deliberately a plain Tkinter window (stdlib, no extra install) rather
than a Flask/Starlette page - it only needs to spawn/inspect/kill local
processes and stream their stdout, none of which a browser tab can do on
its own, so there's no reason to run a web server just for this.

Layout: a sidebar with two tabs.
- Servers: every autodetected template. Selecting one shows its flags
  (port + whatever `set NAME=value` lines its bat defines, e.g.
  ai_agent's AI_AGENT_PROVIDER, plus an Extra-args field when the bat
  forwards %*) with a Start button. If the chosen port is already taken,
  the next free one is used automatically and the status bar says so.
- Instances: every instance this tool has started (or is still tracking
  after it exited). Selecting one shows its live stdout/stderr tail plus
  Stop/Restart.

Limitation, by design: a server started outside this tool (by hand, or
by a stray run_*.bat window) has no Popen handle here, so it can't appear
under Instances - there's nothing to read logs from or relaunch it with.
"""

from __future__ import annotations

import collections
import json
import os
import queue
import re
import shlex
import socket
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import messagebox, simpledialog
from typing import Callable

ROOT = Path(__file__).resolve().parent
ASSETS_DIR = ROOT / "server_launcher" / "assets"
_PRESETS_PATH = ROOT / "server_launcher" / "presets.json"
_GROUPS_PATH = ROOT / "server_launcher" / "groups.json"
# Written on close only when the user chooses to leave running instances in
# the background instead of stopping them - the (template, port) pairs to
# re-adopt on the next launch. Consumed (deleted) as soon as it's read, so
# it never goes stale - see LauncherWindow._adopt_running_instances().
_KEPT_RUNNING_PATH = ROOT / "server_launcher" / "kept_running.json"

# Hint text shown under the "Extra args" field for templates that support
# it, keyed by ServerTemplate.key - not auto-derived from the target
# project's own --help (a hardcoded entry per project isn't worth a
# --help-parsing mechanism for just two of them); add an entry here if
# another project's run.bat starts forwarding %* too.
_EXTRA_ARGS_HINTS = {
    "ai_agent": (
        "--gateway <name>   override the LLM gateway, e.g. openrouter, bedrock, vertex, "
        "litellm, helicone, portkey (anthropic) or azure, together, groq, fireworks, "
        "deepinfra, perplexity, ollama, vllm (openai)\n"
        "--role <name>      override the persona role, e.g. ops_specialist "
        "(configs/config_ai_agent_roles.json)\n"
        "--mcp-url <url>    override the mcp_server URL this agent connects to, "
        "e.g. http://127.0.0.1:8010/mcp"
    ),
    "chat_app": (
        "--mcp-url <url>    override the mcp_server URL this app connects to, "
        "e.g. http://127.0.0.1:8010/mcp"
    ),
}

_VENV_RE = re.compile(r'call\s+\.venv_(\w+)\\Scripts\\activate')
# Excludes "py -m venv ..." (the bootstrap line) so this finds the actual
# run command (py -m src.run / py -m src.server) regardless of where in
# the bat the bootstrap block sits relative to it.
_MODULE_RE = re.compile(r'py\s+-m\s+(?!venv\b)(\S+)')
# Not anchored to line-start: ai_agent's run.bat sets its defaults via
# `if not defined X set X=value`, so `set` doesn't always open the line.
_SET_VAR_RE = re.compile(r"(?:^|\s)set\s+([A-Za-z_][A-Za-z0-9_]*)=([^\r\n]*)", re.IGNORECASE | re.MULTILINE)
# `REM LABEL: ...` / `REM DESCRIPTION: ...` - a run.bat's own self-declared
# display name/blurb for server_launcher.py, so relabeling a server is a
# one-line edit in the bat instead of touching launcher code.
_LABEL_RE = re.compile(r"^\s*REM\s+LABEL:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_DESCRIPTION_RE = re.compile(r"^\s*REM\s+DESCRIPTION:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)

# Port env var + default for a project whose bat doesn't `set` its own
# port (mcp_server/chat_app/catalog_service each read one straight from
# their own config/run.py - see MCP_PORT/CHAT_APP_PORT/CATALOG_PORT).
# ai_agent needs no entry here: its bat already `set`s AI_AGENT_PORT
# itself, picked up generically below.
_PROJECT_PORT_ENV = {
    "mcp_server": ("MCP_PORT", 8010),
    "chat_app": ("CHAT_APP_PORT", 5000),
    "catalog_service": ("CATALOG_PORT", 8020),
}

_POLL_MS = 500
_RESTART_WAIT_SECONDS = 6

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


class _HoverCanvas(tk.Canvas):
    """Shared hover animation for RoundedButton/RoundedCard: on an
    unselected, clickable widget, hovering eases in a diagonal light/dark
    split (light bottom-left, dark top-right) and eases back out on leave.
    Selected or non-interactive (command=None) widgets skip it entirely -
    a hover cue on something already emphasized, or on nothing clickable,
    would just be noise."""

    def __init__(self, *args, selected: bool = False, hoverable: bool = True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.selected = selected
        self.hoverable = hoverable
        self._hover_t = 0.0
        self._hover_after_id: str | None = None
        # Set only while a select-sweep (see RoundedButton.set_selected) is
        # in flight or just finished - overrides what _draw_hover_sheen
        # reveals, from a lightened version of the current fill to the
        # actual destination color, so selecting reads as the same
        # left-to-right gesture as hover/press instead of a flat cross-fade.
        self._reveal_target: str | None = None
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")

    def _on_enter(self, _event=None) -> None:
        if self.hoverable and not self.selected:
            self._animate_hover(1.0)

    def _on_leave(self, _event=None) -> None:
        self._animate_hover(0.0)

    def _flash_press(self) -> None:
        """Replays the left-to-right sweep on click, as press feedback -
        restarts it from 0 even if already mid- or fully-swept-in from
        hover, so a click always gets its own visible sweep rather than
        landing on an already-settled sheen. Eases back out normally on
        <Leave> afterward, same as a hover-triggered sweep."""
        if not self.hoverable or self.selected:
            return
        self._hover_t = 0.0
        self._animate_hover(1.0)

    def _animate_hover(self, target: float) -> None:
        if self._hover_after_id is not None:
            self.after_cancel(self._hover_after_id)
            self._hover_after_id = None
        start_t = self._hover_t
        start_time = time.perf_counter()

        def step() -> None:
            if not self.winfo_exists():
                return
            elapsed = time.perf_counter() - start_time
            frac = min(1.0, elapsed / (_HOVER_DURATION_MS / 1000))
            self._hover_t = start_t + (target - start_t) * _ease_in_out(frac)
            self._redraw()
            if frac < 1.0:
                self._hover_after_id = self.after(16, step)
            else:
                self._hover_after_id = None

        step()

    def _draw_hover_sheen(self, x1: float, y1: float, x2: float, y2: float) -> None:
        """Light wedge that wipes in from the left as hover_t goes 0->1 (and
        back out on leave) instead of fading in place - a reveal, not a
        cross-fade. The full-coverage shape is the single-diagonal triangle
        (x1,y2)-(x2,y2)-(x1,y1); a vertical reveal line at x1+hover_t*(x2-x1)
        clips it, so the visible piece is always bounded by that one
        straight hypotenuse (never chamfered/segmented - stays crisp) plus
        the reveal line itself. No-op while there's nothing to show."""
        if self._hover_t <= 0.01 or x2 <= x1:
            return
        light = self._reveal_target if self._reveal_target is not None else _lighten(self.fill, _HOVER_LIGHTEN)
        reveal_x = min(x2, x1 + self._hover_t * (x2 - x1))
        y_line = y1 + (reveal_x - x1) / (x2 - x1) * (y2 - y1)
        self.create_polygon(
            x1, y2,
            reveal_x, y2,
            reveal_x, y_line,
            x1, y1,
            fill=light, outline="",
        )


def _rounded_rect_points(x1: float, y1: float, x2: float, y2: float, radius: float) -> list[float]:
    """Point list for a smoothed polygon approximating a rounded rect -
    Tk canvases have no native border-radius, so every "rounded" widget
    in this file draws one of these instead of a plain rectangle."""
    radius = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
    return [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]


class RoundedButton(_HoverCanvas):
    """A clickable rounded-rect chip with centered text - used for the
    tab toggle and Start/Stop/Restart. Redraws on <Configure> so it still
    looks right when packed with fill="x"/expand (sized by the geometry
    manager, not just its own text)."""

    def __init__(
        self, parent, text: str, command=None, *, bg: str, fill: str, outline: str, fg: str,
        font=("Segoe UI", 10), radius: int = _RADIUS, padx: int = 14, pady: int = 6, selected: bool = False,
    ) -> None:
        super().__init__(
            parent, bg=bg, highlightthickness=0, bd=0, cursor="hand2" if command else "arrow",
            selected=selected, hoverable=command is not None,
        )
        self.command = command
        self.fill = fill
        self.outline = outline
        self.fg = fg
        self.text = text
        self.font = font
        self.radius = radius

        probe = self.create_text(0, 0, text=text, font=font, anchor="nw")
        bbox = self.bbox(probe)
        self.delete(probe)
        self._min_w = (bbox[2] - bbox[0]) + 2 * padx
        self._min_h = (bbox[3] - bbox[1]) + 2 * pady
        self.config(width=self._min_w, height=self._min_h)

        self.bind("<Configure>", self._redraw)
        self.bind("<Button-1>", self._on_click)
        self._redraw()

    def _redraw(self, _event=None) -> None:
        w = self.winfo_width() if self.winfo_width() > 1 else self._min_w
        h = self.winfo_height() if self.winfo_height() > 1 else self._min_h
        self.delete("all")
        points = _rounded_rect_points(1, 1, w - 1, h - 1, self.radius)
        self.create_polygon(points, smooth=True, fill=self.fill, outline="")
        self._draw_hover_sheen(1, 1, w - 1, h - 1)
        self.create_polygon(points, smooth=True, fill="", outline=self.outline, width=1)
        self.create_text(w / 2, h / 2, text=self.text, fill=self.fg, font=self.font)

    def _on_click(self, _event) -> None:
        self._flash_press()
        if self.command:
            self.command()

    def set_fill(self, fill: str) -> None:
        self.fill = fill
        self._redraw()

    def set_selected(self, selected: bool, fill: str) -> None:
        """For the Servers/Instances tab toggle. The button being pressed
        (selected=True) plays the SAME left-to-right sweep as hover/press,
        wiping from its current fill straight to the destination color (via
        _reveal_target, not a lighten-in-place) - once fully revealed, that
        color becomes the resting fill and the overlay clears, so a later
        hover/press sweeps normally again from there. The OTHER button
        losing selection (selected=False) wasn't what the user pressed, so
        it just snaps straight to its resting color with no animation -
        playing the same sweep there too would read as if two buttons had
        been pressed at once."""
        self.selected = selected
        if self._hover_after_id is not None:
            self.after_cancel(self._hover_after_id)
            self._hover_after_id = None

        if not selected:
            self._hover_t = 0.0
            self._reveal_target = None
            self.fill = fill
            self._redraw()
            return

        self._hover_t = 0.0
        self._reveal_target = fill
        start_time = time.perf_counter()

        def step() -> None:
            if not self.winfo_exists():
                return
            elapsed = time.perf_counter() - start_time
            frac = min(1.0, elapsed / (_HOVER_DURATION_MS / 1000))
            self._hover_t = _ease_in_out(frac)
            self._redraw()
            if frac < 1.0:
                self._hover_after_id = self.after(16, step)
            else:
                self._hover_after_id = None
                self.fill = fill
                self._hover_t = 0.0
                self._reveal_target = None
                self._redraw()

        step()

    def set(self, *, text: str | None = None, fill: str | None = None, fg: str | None = None) -> None:
        """Updates whichever of text/fill/fg are given and redraws once -
        used for the Instances status badge, whose text and color both
        change together on every status transition."""
        if text is not None:
            self.text = text
        if fill is not None:
            self.fill = fill
        if fg is not None:
            self.fg = fg
        self._redraw()


class RoundedCard(_HoverCanvas):
    """A clickable rounded-rect row: icon + name (left, expands) + a
    secondary right-aligned label (port) - used for every Servers/
    Instances sidebar entry. One canvas per row (not per-element Labels
    on a Frame) so the rounded background can actually be drawn."""

    def __init__(
        self, parent, *, bg: str, fill: str, outline: str, fg: str, fg_dim: str,
        icon: str = "", name: str, secondary: str = "", command=None, dot_color: str | None = None,
        font=("Segoe UI", 10), radius: int = _RADIUS, height: int = 40, selected: bool = False,
    ) -> None:
        super().__init__(
            parent, bg=bg, highlightthickness=0, bd=0, height=height,
            cursor="hand2" if command else "arrow", selected=selected, hoverable=command is not None,
        )
        self.fill = fill
        self.outline = outline
        self.fg = fg
        self.fg_dim = fg_dim
        self.icon = icon
        # A status dot is drawn as a filled circle (with its own outline),
        # not colored text - green/red can be dark enough that colored text
        # on this app's near-black background would be unreadable, but a
        # filled shape stays visible via its outline regardless of fill.
        self.dot_color = dot_color
        self.name = name
        self.secondary = secondary
        self.font = font
        self.radius = radius
        self._min_h = height
        self.command = command

        self.bind("<Configure>", self._redraw)
        self.bind("<Button-1>", self._on_click)
        self._redraw()

    def _redraw(self, _event=None) -> None:
        w = self.winfo_width() if self.winfo_width() > 1 else 200
        h = self.winfo_height() if self.winfo_height() > 1 else self._min_h
        self.delete("all")
        points = _rounded_rect_points(1, 1, w - 1, h - 1, self.radius)
        self.create_polygon(points, smooth=True, fill=self.fill, outline="")
        self._draw_hover_sheen(1, 1, w - 1, h - 1)
        self.create_polygon(points, smooth=True, fill="", outline=self.outline, width=1)
        if self.dot_color is not None:
            r = 5
            self.create_oval(16 - r, h / 2 - r, 16 + r, h / 2 + r, fill=self.dot_color, outline=self.fg_dim, width=1)
        elif self.icon:
            self.create_text(16, h / 2, text=self.icon, fill=self.fg_dim, font=("Segoe UI", 11), anchor="w")
        self.create_text(38, h / 2, text=self.name, fill=self.fg, font=self.font, anchor="w")
        if self.secondary:
            self.create_text(w - 12, h / 2, text=self.secondary, fill=self.fg_dim, font=self.font, anchor="e")

    def _on_click(self, _event) -> None:
        self._flash_press()
        if self.command:
            self.command()

    def set_fill(self, fill: str) -> None:
        self.fill = fill
        self._redraw()

    def set_dot_color(self, color: str) -> None:
        self.dot_color = color
        self._redraw()


class PresetChip(_HoverCanvas):
    """One rounded pill for a saved preset: name (click = apply) on the
    left, a thin divider, then a trash icon (click = remove) on the right -
    drawn as ONE canvas with ONE border, so the hover/press sweep plays
    across the whole pill as a single piece rather than as two separately-
    bordered buttons each animating on their own."""

    _TRASH_ZONE_W = 34

    def __init__(
        self, parent, name: str, *, on_apply: Callable[[], None], on_remove: Callable[[], None],
        bg: str, fill: str, outline: str, fg: str, font=("Segoe UI", 10), padx: int = 14, pady: int = 8,
    ) -> None:
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, cursor="hand2", selected=False, hoverable=True)
        self.name_text = name
        self.on_apply = on_apply
        self.on_remove = on_remove
        self.fill = fill
        self.outline = outline
        self.fg = fg
        self.font = font
        self.padx = padx

        probe = self.create_text(0, 0, text=name, font=font, anchor="nw")
        bbox = self.bbox(probe)
        self.delete(probe)
        self._min_h = (bbox[3] - bbox[1]) + 2 * pady
        self.radius = self._min_h / 2  # full capsule, not just a rounded rect
        self._min_w = padx + (bbox[2] - bbox[0]) + padx + self._TRASH_ZONE_W
        self._divider_x = self._min_w - self._TRASH_ZONE_W
        self.config(width=self._min_w, height=self._min_h)

        self.bind("<Configure>", self._redraw)
        self.bind("<Button-1>", self._on_click)
        self._redraw()

    def _redraw(self, _event=None) -> None:
        w = self.winfo_width() if self.winfo_width() > 1 else self._min_w
        h = self.winfo_height() if self.winfo_height() > 1 else self._min_h
        self.delete("all")
        points = _rounded_rect_points(1, 1, w - 1, h - 1, self.radius)
        self.create_polygon(points, smooth=True, fill=self.fill, outline="")
        self._draw_hover_sheen(1, 1, w - 1, h - 1)
        self.create_polygon(points, smooth=True, fill="", outline=self.outline, width=1)
        self._divider_x = w - self._TRASH_ZONE_W
        self.create_line(self._divider_x, 6, self._divider_x, h - 6, fill=self.outline, width=1)
        self.create_text(self.padx, h / 2, text=self.name_text, fill=self.fg, font=self.font, anchor="w")
        self.create_text(self._divider_x + self._TRASH_ZONE_W / 2, h / 2, text="\U0001F5D1", fill=self.fg, font=self.font)

    def _on_click(self, event) -> None:
        self._flash_press()
        if event.x >= self._divider_x:
            self.on_remove()
        else:
            self.on_apply()


@dataclass
class ServerTemplate:
    key: str
    display_name: str
    description: str
    working_dir: Path
    venv_python: Path
    module: str
    port_env_var: str
    default_port: int
    extra_env_vars: dict[str, str]  # editable flags besides port, e.g. AI_AGENT_PROVIDER
    supports_args: bool  # bat forwards %* to the process it runs


@dataclass
class Preset:
    """A named, saved set of flag values for one template - clicking it
    in the Presets section overwrites the current Port/env-var/Extra-args
    fields with these, the same way it would if typed by hand."""

    name: str
    port: int
    env_vars: dict[str, str] = field(default_factory=dict)
    args: str = ""


@dataclass
class GroupMember:
    template_key: str
    port: int
    extra_env: dict[str, str] = field(default_factory=dict)
    extra_args: str = ""
    preset_name: str | None = None


@dataclass
class ServerGroup:
    name: str
    members: list[GroupMember] = field(default_factory=list)


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


def discover_templates() -> list[ServerTemplate]:
    templates: list[ServerTemplate] = []
    for bat_path in sorted(ROOT.glob("*/run.bat")):
        working_dir = bat_path.parent.resolve()
        project_dir = bat_path.parent.name
        try:
            content = bat_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        venv_m = _VENV_RE.search(content)
        mod_m = _MODULE_RE.search(content)
        if not (venv_m and mod_m):
            # Doesn't match this repo's established run.bat shape - skip
            # rather than guess at how to launch it.
            continue

        venv_python = (working_dir / f".venv_{venv_m.group(1)}" / "Scripts" / "python.exe").resolve()
        module = mod_m.group(1)
        supports_args = "%*" in content

        set_vars = {m.group(1).upper(): m.group(2).strip() for m in _SET_VAR_RE.finditer(content)}
        port_var = next((k for k in set_vars if "PORT" in k), None)
        if port_var:
            default_port = int(set_vars[port_var]) if set_vars[port_var].isdigit() else 8000
        else:
            port_var, default_port = _PROJECT_PORT_ENV.get(project_dir, (f"{project_dir.upper()}_PORT", 8000))
        extra_env_vars = {k: v for k, v in set_vars.items() if k != port_var}

        label_m = _LABEL_RE.search(content)
        desc_m = _DESCRIPTION_RE.search(content)
        label = label_m.group(1) if label_m else project_dir
        description = desc_m.group(1) if desc_m else ""

        display_name = label

        templates.append(
            ServerTemplate(
                key=project_dir,
                display_name=display_name,
                description=description,
                working_dir=working_dir,
                venv_python=venv_python,
                module=module,
                port_env_var=port_var,
                default_port=default_port,
                extra_env_vars=extra_env_vars,
                supports_args=supports_args,
            )
        )
    return templates


def _port_in_use(port: int) -> bool:
    # No SO_REUSEADDR here deliberately: on Windows it lets bind() succeed
    # even while another process is actively LISTENING on the port (unlike
    # Berkeley sockets, where it only relaxes TIME_WAIT) - with it set, this
    # check silently reported free ports that were actually taken.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return True
        return False


def _find_free_port(start_port: int) -> int:
    port = start_port
    while _port_in_use(port):
        port += 1
    return port


def _kill_pid_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)


def _find_pid_on_port(port: int) -> int | None:
    """Best-effort PID of whatever's LISTENING on 127.0.0.1:<port>, parsed
    from `netstat -ano` - used only for the one-time startup adoption scan
    (see LauncherWindow._adopt_running_instances()), never called
    repeatedly from the main thread."""
    result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
            try:
                return int(parts[-1])
            except ValueError:
                continue
    return None


def _pid_alive(pid: int) -> bool:
    """Shells out to `tasklist` - blocking, ~tens of ms. Only ever called
    from Instance's own background liveness-watcher thread for an adopted
    instance, never from the UI thread - see Instance._start_liveness_watcher().
    Calling this from _tick() every poll interval is what froze the app
    before; the watcher thread now does it instead, off-thread, and is_alive()
    just reads the cached result."""
    result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
    return str(pid) in result.stdout


def _run_and_log(cmd: list[str], cwd: Path, log: collections.deque) -> int:
    """Runs `cmd` to completion, streaming its output into `log` line by
    line (same deque the server's own stdout lands in later) rather than
    waiting silently - a first-run venv-create + editable-install can
    take a while, and the Instances log view is the only place watching
    it happens."""
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    for line in proc.stdout:
        log.append(line.rstrip("\n"))
    return proc.wait()


def _ensure_venv(template: ServerTemplate, log: collections.deque) -> bool:
    """Creates `template.venv_python`'s venv and editable-installs the
    project into it if it isn't there yet - mirrors the same
    if-not-exist bootstrap block each run.bat carries for anyone running
    it directly instead of through this tool. Returns False on failure."""
    if template.venv_python.exists():
        return True
    venv_dir = template.venv_python.parent.parent
    log.append(f"Creating virtual environment {venv_dir.name} ...")
    if _run_and_log(["py", "-m", "venv", str(venv_dir)], template.working_dir, log) != 0:
        log.append("Failed to create the virtual environment.")
        return False
    log.append(f"Installing {template.working_dir.name} in editable mode ...")
    if _run_and_log([str(template.venv_python), "-m", "pip", "install", "-e", ".[dev]"], template.working_dir, log) != 0:
        log.append("Failed to install dependencies.")
        return False
    log.append("Virtual environment ready.")
    return True


def _build_launch_args(
    template: ServerTemplate, port: int, extra_env: dict[str, str], extra_args: str,
) -> tuple[list[str], dict[str, str]]:
    env = {**os.environ, template.port_env_var: str(port), **extra_env}
    cmd = [str(template.venv_python), "-m", template.module]
    if template.supports_args and extra_args.strip():
        cmd += shlex.split(extra_args.strip())
    return cmd, env


def _spawn(template: ServerTemplate, port: int, extra_env: dict[str, str], extra_args: str) -> subprocess.Popen:
    cmd, env = _build_launch_args(template, port, extra_env, extra_args)
    return subprocess.Popen(
        cmd,
        cwd=template.working_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _spawn_detached(template: ServerTemplate, port: int, extra_env: dict[str, str], extra_args: str) -> None:
    """Like _spawn(), but with stdout/stderr discarded instead of piped, and
    no reader thread - used only when handing an instance off to survive
    this app's exit ("keep running in background"). Confirmed by testing: a
    piped Popen whose read end lives in this process, actively read by a
    background thread, reliably dies along with this process at interpreter
    shutdown (the reader thread gets torn down mid-syscall on the pipe). A
    process with no pipe tied to us at all has no such dependency and
    survives fine - the trade-off is losing its log history once handed off
    this way, which is unavoidable since nothing would be left to read it."""
    cmd, env = _build_launch_args(template, port, extra_env, extra_args)
    subprocess.Popen(
        cmd,
        cwd=template.working_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


class Instance:
    def __init__(
        self, template: ServerTemplate, port: int, extra_env: dict[str, str], extra_args: str,
        *, adopted_pid: int | None = None, preset_name: str | None = None,
    ) -> None:
        self.id = f"{template.key}:{port}:{int(time.time() * 1000)}"
        self.template = template
        self.port = port
        self.extra_env = extra_env
        self.extra_args = extra_args
        # An adopted process was not launched from this window, so it has no
        # trustworthy preset provenance. Self-started instances receive the
        # selected preset name from the server form instead.
        self.preset_name = preset_name
        self.log_lines: collections.deque[str] = collections.deque(maxlen=4000)
        self.process: subprocess.Popen | None = None
        # Set only when this Instance wraps a process this window didn't
        # spawn itself (found already listening on a template's default
        # port at startup). There's no Popen handle for one of these, so
        # is_alive()/stop() fall back to a PID instead - see
        # _start_liveness_watcher() for why is_alive() never blocks.
        self._adopted_pid = adopted_pid
        self._adopted_alive = True
        # "running" | "stopping" | "exited" | "failed", plus "starting" as a
        # plain (uncolored, not notified) placeholder before the first real
        # transition - "initializing"/"restarting" as their own tracked,
        # colored states were removed: both were too short-lived to ever
        # reliably show up (venv-already-exists / a fast kill routinely
        # finished before a single redraw), so they never actually worked
        # as a visible feature. Every REAL transition runs through
        # _set_status() so on_status_change fires immediately (passed the
        # status string itself, not just a "something changed" ping) instead
        # of waiting for the next poll tick and re-reading self.status then,
        # which could land on a later status and skip the one just set.
        self.on_status_change: Callable[[str], None] | None = None
        # Bumped by _launch() so a stale reader thread from a launch that's
        # since been superseded (restart's OLD process finally hitting
        # stdout EOF after the NEW one from _launch() is already running)
        # can't clobber the current status back to "exited" - it only ever
        # applies a status if its own generation is still the current one.
        self._generation = 0
        if adopted_pid is not None:
            self.log_lines.append(
                f"--- adopted an already-running process on port {port} (PID {adopted_pid}) from "
                "a previous launcher session - log output from before this point is unavailable ---"
            )
            self._set_status("running")
            self._start_liveness_watcher()
        else:
            self.status = "starting"
            self._launch()

    def _set_status(self, status: str) -> None:
        self.status = status
        if self.on_status_change is not None:
            self.on_status_change(status)

    def _launch(self) -> None:
        self._generation += 1
        generation = self._generation
        threading.Thread(target=self._boot_and_run, args=(generation,), daemon=True).start()

    def _boot_and_run(self, generation: int) -> None:
        def set_status(status: str) -> None:
            if generation == self._generation:
                self._set_status(status)

        if not _ensure_venv(self.template, self.log_lines):
            set_status("failed")
            return
        set_status("running")
        process = _spawn(self.template, self.port, self.extra_env, self.extra_args)
        self.process = process
        try:
            for line in process.stdout:  # closes/ends when the process exits
                self.log_lines.append(line.rstrip("\n"))
        except (OSError, ValueError):
            pass
        set_status("exited")

    def _start_liveness_watcher(self) -> None:
        """Adopted instances have no Popen handle for a cheap poll() check -
        is_alive() would otherwise have to shell out (tasklist) every time
        it's called, INCLUDING from _tick() on the main thread every poll
        interval - that repeated blocking call is what froze the UI before.
        This background thread does the blocking check instead, on its own
        schedule, and is_alive() just reads the cached result - a plain
        attribute read, safe to call from anywhere including the UI thread."""
        def watch() -> None:
            while self.process is None and self._adopted_pid is not None:
                alive = _pid_alive(self._adopted_pid)
                self._adopted_alive = alive
                if not alive:
                    if self.process is None:  # nothing (e.g. restart) took over meanwhile
                        self._set_status("exited")
                    return
                time.sleep(_POLL_MS / 1000)

        threading.Thread(target=watch, daemon=True).start()

    def is_alive(self) -> bool:
        if self.process is not None:
            return self.process.poll() is None
        if self._adopted_pid is not None:
            return self._adopted_alive
        return False

    def stop(self) -> None:
        self._set_status("stopping")
        if self.process is not None:
            _kill_pid_tree(self.process.pid)
        elif self._adopted_pid is not None:
            _kill_pid_tree(self._adopted_pid)

    def restart(self) -> None:
        self.stop()  # status stays "stopping" through the wait below - no separate "restarting" state
        deadline = time.time() + _RESTART_WAIT_SECONDS
        while time.time() < deadline and self.is_alive():
            time.sleep(0.2)
        self.log_lines.append(f"--- restarting on port {self.port} ---")
        self._launch()


class LauncherWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Server Launcher")
        root.configure(bg=_BG)
        root.geometry("820x560")

        # Instance status changes arrive from background threads (one per
        # instance) and must never touch Tk directly from there - Tk is not
        # thread-safe, and calling root.after() from several threads at once
        # (as happened with Kill Instances stopping many instances together)
        # could hang the whole app. Background threads only ever push here;
        # only _drain_status_queue(), running on the main thread via its own
        # root.after loop, ever reads it or touches a widget.
        self._status_queue: queue.Queue[tuple[str, str]] = queue.Queue()

        self.templates = discover_templates()
        self.instances: dict[str, Instance] = {}
        self._adopt_running_instances()
        self.presets: dict[str, list[Preset]] = _load_presets()
        self.groups: dict[str, ServerGroup] = _load_groups()
        self._empty_state_image = self._load_empty_state_image()

        self.active_tab = "servers"
        self.selected_template: ServerTemplate | None = None
        self.selected_instance_id: str | None = None
        self.selected_group_name: str | None = None
        self.instance_dots: dict[str, RoundedCard] = {}

        self._last_log_len = -1
        self._log_text: tk.Text | None = None
        self._status_label: RoundedButton | None = None

        root.grid_rowconfigure(1, weight=1)
        # column 0 = sidebar (fixed), column 1 = separator (1px), column 2 = main (flexible).
        # minsize on column 0 pins the sidebar's width at the grid level too, so it can't
        # drift between tabs even if a card's content briefly requests a different width.
        root.grid_columnconfigure(0, minsize=_SIDEBAR_WIDTH)
        root.grid_columnconfigure(2, weight=1)

        tabbar = tk.Frame(root, bg=_BG)
        tabbar.grid(row=0, column=0, columnspan=3, sticky="ew", padx=10, pady=(10, 6))
        self.servers_tab_btn = RoundedButton(
            tabbar, "Servers", command=lambda: self._set_tab("servers"),
            bg=_BG, fill=_ROW_SELECTED, outline=_BORDER, fg=_FG,
        )
        self.servers_tab_btn.pack(side="left", padx=(0, 4))
        self.instances_tab_btn = RoundedButton(
            tabbar, "Instances", command=lambda: self._set_tab("instances"),
            bg=_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        )
        self.instances_tab_btn.pack(side="left", padx=(0, 4))
        self.groups_tab_btn = RoundedButton(
            tabbar, "Groups", command=lambda: self._set_tab("groups"),
            bg=_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        )
        self.groups_tab_btn.pack(side="left")

        sidebar = tk.Frame(root, bg=_SIDEBAR_BG, width=_SIDEBAR_WIDTH)
        sidebar.grid(row=1, column=0, sticky="ns")
        # sidebar's own children are pack-managed, not
        # grid-managed, so pack_propagate is the one that actually pins this
        # frame's width - grid_propagate would be a no-op here and let a
        # card's content silently resize the sidebar between tabs.
        sidebar.pack_propagate(False)

        separator = tk.Frame(root, bg=_SEPARATOR, width=1)
        separator.grid(row=1, column=1, sticky="ns")

        # Packed (side="bottom") before sidebar_list so it claims its slice
        # of the cavity first - sidebar_list (packed after, expand+fill
        # both, default side="top") then fills everything left above it.
        bottom_actions = tk.Frame(sidebar, bg=_SIDEBAR_BG)
        bottom_actions.pack(side="bottom", fill="x", padx=10, pady=10)
        self._instance_actions = bottom_actions
        bottom_row = tk.Frame(bottom_actions, bg=_SIDEBAR_BG)
        bottom_row.pack(fill="x")
        self._instance_actions_row = bottom_row
        self._kill_instances_button = RoundedButton(
            bottom_row, "Kill Instances", command=self._kill_all_instances,
            bg=_SIDEBAR_BG, fill=_RED, outline=_RED, fg=_FG,
        )
        self._kill_instances_button.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self._refresh_button = RoundedButton(
            bottom_row, "⟳", command=self._refresh_active_tab,
            bg=_SIDEBAR_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG, padx=10,
        )
        self._refresh_button.pack(side="left")
        self._clear_closed_button = RoundedButton(
            bottom_actions, "Clear Closed", command=self._clear_closed_instances,
            bg=_SIDEBAR_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        )
        self._restart_all_button = RoundedButton(
            bottom_actions, "Restart All", command=self._restart_all_instances,
            bg=_SIDEBAR_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        )
        self._create_group_button = RoundedButton(
            bottom_actions, "Create Group", command=self._show_create_group_dialog,
            bg=_SIDEBAR_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        )

        self.sidebar_list = tk.Frame(sidebar, bg=_SIDEBAR_BG)
        self.sidebar_list.pack(fill="both", expand=True, padx=8)

        self.main = tk.Frame(root, bg=_BG)
        self.main.grid(row=1, column=2, sticky="nsew")

        self.status = tk.Label(root, text="", bg=_BG, fg=_FG, anchor="w")
        self.status.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 6))

        self._set_tab("servers")
        self._tick()
        self._drain_status_queue()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- tabs / sidebar -------------------------------------------------

    def _set_tab(self, tab: str) -> None:
        self.active_tab = tab
        self.servers_tab_btn.set_selected(tab == "servers", _ROW_SELECTED if tab == "servers" else _ROW_BG)
        self.instances_tab_btn.set_selected(tab == "instances", _ROW_SELECTED if tab == "instances" else _ROW_BG)
        self.groups_tab_btn.set_selected(tab == "groups", _ROW_SELECTED if tab == "groups" else _ROW_BG)
        if tab == "instances":
            self._instance_actions.pack(side="bottom", fill="x", padx=10, pady=10, before=self.sidebar_list)
            self._kill_instances_button.pack(side="left", expand=True, fill="x", padx=(0, 4))
            self._refresh_button.pack(side="left")
            self._clear_closed_button.pack(
                fill="x", pady=(0, 6), before=self._instance_actions_row,
            )
            self._restart_all_button.pack(
                fill="x", pady=(0, 6), before=self._clear_closed_button,
            )
            self._create_group_button.pack(
                fill="x", pady=(0, 6), before=self._restart_all_button,
            )
        else:
            self._create_group_button.pack_forget()
            self._restart_all_button.pack_forget()
            self._clear_closed_button.pack_forget()
            if tab == "servers":
                self._instance_actions.pack(side="bottom", fill="x", padx=10, pady=10, before=self.sidebar_list)
                self._kill_instances_button.pack_forget()
                self._refresh_button.pack(side="left")
            else:
                self._instance_actions.pack_forget()
        self._render_sidebar()
        if tab == "servers":
            self._render_server_detail(self.selected_template)
        elif tab == "instances":
            self._render_instance_detail(self.selected_instance_id)
        else:
            self._render_group_detail(self.selected_group_name)

    def _render_sidebar(self) -> None:
        for child in self.sidebar_list.winfo_children():
            child.destroy()
        self.instance_dots.clear()

        if self.active_tab == "servers":
            if not self.templates:
                tk.Label(self.sidebar_list, text="No run.bat found.", bg=_SIDEBAR_BG, fg=_DIM_FG).pack(pady=8)
            for template in self.templates:
                selected = template is self.selected_template
                card = RoundedCard(
                    self.sidebar_list,
                    bg=_SIDEBAR_BG, fill=_ROW_SELECTED if selected else _ROW_BG, outline=_BORDER,
                    fg=_FG, fg_dim=_DIM_FG, icon="☷", name=template.display_name,
                    secondary=f":{template.default_port}", selected=selected,
                    command=lambda t=template: self._select_template(t),
                )
                card.pack(fill="x", pady=3)
        elif self.active_tab == "instances":
            if not self.instances:
                tk.Label(self.sidebar_list, text="Nothing started yet.", bg=_SIDEBAR_BG, fg=_DIM_FG).pack(pady=8)
            for instance in self.instances.values():
                selected = instance.id == self.selected_instance_id
                card = RoundedCard(
                    self.sidebar_list,
                    bg=_SIDEBAR_BG, fill=_ROW_SELECTED if selected else _ROW_BG, outline=_BORDER,
                    fg=_FG, fg_dim=_DIM_FG, name=instance.template.display_name,
                    secondary=f":{instance.port}",
                    dot_color=_GREEN if instance.is_alive() else _DIM_FG,
                    selected=selected, command=lambda i=instance: self._select_instance(i.id),
                )
                card.pack(fill="x", pady=3)
                self.instance_dots[instance.id] = card
        else:
            if not self.groups:
                tk.Label(self.sidebar_list, text="No groups saved yet.", bg=_SIDEBAR_BG, fg=_DIM_FG).pack(pady=8)
            for group in self.groups.values():
                selected = group.name == self.selected_group_name
                card = RoundedCard(
                    self.sidebar_list,
                    bg=_SIDEBAR_BG, fill=_ROW_SELECTED if selected else _ROW_BG, outline=_BORDER,
                    fg=_FG, fg_dim=_DIM_FG, icon="☷", name=group.name,
                    selected=selected, command=lambda name=group.name: self._select_group(name),
                )
                card.pack(fill="x", pady=3)

    # ---- servers tab -----------------------------------------------------

    def _select_template(self, template: ServerTemplate) -> None:
        self.selected_template = template
        self._render_sidebar()
        self._render_server_detail(template)

    def _select_group(self, group_name: str) -> None:
        self.selected_group_name = group_name
        self._render_sidebar()
        self._render_group_detail(group_name)

    def _live_group_members(self) -> list[GroupMember]:
        """Return independent recipe snapshots for instances still running."""
        return [
            GroupMember(
                instance.template.key,
                instance.port,
                dict(instance.extra_env),
                instance.extra_args,
                instance.preset_name,
            )
            for instance in self.instances.values()
            if instance.is_alive()
        ]

    def _save_group(self, name: str, members: list[GroupMember]) -> bool:
        """Save a named recipe, asking before an existing recipe is replaced."""
        if name in self.groups and not messagebox.askyesno(
            "Replace group",
            f"Replace the saved group {name!r}?",
            parent=self.root,
        ):
            return False
        self.groups[name] = ServerGroup(name, members)
        _save_groups(self.groups)
        return True

    def _show_create_group_dialog(self) -> None:
        members = self._live_group_members()
        if not members:
            messagebox.showinfo("Create Group", "No running instances to save.", parent=self.root)
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Create Group")
        dialog.configure(bg=_BG)
        dialog.resizable(False, False)
        tk.Label(dialog, text="Group name", bg=_BG, fg=_FG).pack(
            anchor="w", padx=16, pady=(16, 4)
        )
        name_var = tk.StringVar()
        name_entry = tk.Entry(dialog, textvariable=name_var, bg=_FIELD_BG, fg=_FG, insertbackground=_FG)
        name_entry.pack(fill="x", padx=16)
        selected: list[tuple[str, Instance, tk.BooleanVar]] = []
        tk.Label(dialog, text="Running instances", bg=_BG, fg=_DIM_FG).pack(
            anchor="w", padx=16, pady=(16, 4)
        )
        live_instances = [
            (instance_id, instance) for instance_id, instance in self.instances.items() if instance.is_alive()
        ]
        for instance_id, instance in live_instances:
            checked = tk.BooleanVar(value=True)
            selected.append((instance_id, instance, checked))
            tk.Checkbutton(
                dialog, text=f"{instance.template.key} :{instance.port}", variable=checked,
                bg=_BG, fg=_FG, selectcolor=_FIELD_BG, activebackground=_BG, activeforeground=_FG,
            ).pack(anchor="w", padx=16)

        actions = tk.Frame(dialog, bg=_BG)
        actions.pack(fill="x", padx=16, pady=16)

        def save() -> None:
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Create Group", "Enter a group name.", parent=dialog)
                return
            chosen = []
            for instance_id, original_instance, checked in selected:
                instance = self.instances.get(instance_id)
                if checked.get():
                    if instance is not original_instance or not instance.is_alive():
                        messagebox.showerror("Create Group", "A selected instance is no longer running.", parent=dialog)
                        return
                    chosen.append(GroupMember(instance.template.key, instance.port, dict(instance.extra_env), instance.extra_args, instance.preset_name))
            if not chosen:
                messagebox.showerror("Create Group", "Choose at least one instance.", parent=dialog)
                return
            if not self._save_group(name, chosen):
                return
            dialog.destroy()
            self._set_tab("groups")
            self._select_group(name)

        RoundedButton(
            actions, "Cancel", command=dialog.destroy, bg=_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        ).pack(side="right")
        RoundedButton(
            actions, "Save", command=save, bg=_BG, fill=_GREEN, outline=_GREEN, fg=_FG,
        ).pack(side="right", padx=(0, 6))
        name_entry.focus_set()

    def _delete_group(self, group_name: str) -> None:
        if group_name not in self.groups:
            return
        if not messagebox.askyesno(
            "Delete group", f"Delete the saved group {group_name!r}?", parent=self.root,
        ):
            return
        del self.groups[group_name]
        _save_groups(self.groups)
        if self.selected_group_name == group_name:
            self.selected_group_name = None
        self._render_sidebar()
        if self.active_tab == "groups":
            self._render_group_detail(self.selected_group_name)

    def _group_start_issues(self, group: ServerGroup) -> list[str]:
        templates = {template.key: template for template in self.templates}
        issues = []
        requested_ports: set[int] = set()
        for member in group.members:
            if (
                not isinstance(member.template_key, str)
                or not isinstance(member.port, int) or isinstance(member.port, bool)
                or not isinstance(member.extra_env, dict)
                or not isinstance(member.extra_args, str)
                or member.preset_name is not None and not isinstance(member.preset_name, str)
            ):
                issues.append("Saved group contains an invalid member configuration.")
                continue
            if member.port in requested_ports:
                issues.append(f"Port {member.port} is requested by more than one group member.")
                continue
            requested_ports.add(member.port)
            template = templates.get(member.template_key)
            if template is None:
                issues.append(f"Missing server template: {member.template_key}.")
            elif _port_in_use(member.port):
                issues.append(
                    f"Port {member.port} is already in use for {template.display_name}."
                )
        return issues

    def _start_group(self, group_name: str) -> None:
        group = self.groups.get(group_name)
        if group is None:
            return
        issues = self._group_start_issues(group)
        if issues:
            messagebox.showerror("Start Group", "\n".join(issues), parent=self.root)
            return

        templates = {template.key: template for template in self.templates}
        instance_ids = []
        for member in group.members:
            instance = Instance(
                templates[member.template_key], member.port, dict(member.extra_env),
                member.extra_args, preset_name=member.preset_name,
            )
            self._wire_instance(instance)
            self.instances[instance.id] = instance
            instance_ids.append(instance.id)
        self.status.config(text=f"Started group {group.name!r} ({len(instance_ids)} instances).")
        self._set_tab("instances")
        if instance_ids:
            self._select_instance(instance_ids[0])

    def _clear_main(self) -> None:
        for child in self.main.winfo_children():
            child.destroy()
        self._log_text = None
        self._status_label = None

    def _load_empty_state_image(self) -> tk.PhotoImage | None:
        image_path = ASSETS_DIR / "server.png"
        if not image_path.exists():
            return None
        try:
            # subsample(4): the source is 512x512, way bigger than this
            # panel needs - Tk's PhotoImage only downsizes by an integer
            # factor (no smooth resize built in), 4 lands close to the
            # ~100-130px icon size this empty state calls for.
            return tk.PhotoImage(file=str(image_path)).subsample(4)
        except tk.TclError:
            return None

    def _render_empty_state(self, title: str, subtitle: str) -> None:
        wrapper = tk.Frame(self.main, bg=_BG)
        wrapper.place(relx=0.5, rely=0.5, anchor="center")
        if self._empty_state_image is not None:
            tk.Label(wrapper, image=self._empty_state_image, bg=_BG).pack(pady=(0, 16))
        tk.Label(wrapper, text=title, bg=_BG, fg=_FG, font=("Segoe UI", 13, "bold")).pack()
        tk.Label(wrapper, text=subtitle, bg=_BG, fg=_DIM_FG).pack(pady=(4, 0))

    def _render_group_detail(self, group_name: str | None) -> None:
        self._clear_main()
        if group_name is None:
            self._render_empty_state("Groups", "Select a group.")
            return

        group = self.groups.get(group_name)
        if group is None:
            self._render_empty_state("Groups", "Select a group.")
            return

        header = tk.Frame(self.main, bg=_BG)
        header.pack(fill="x", padx=16, pady=(16, 8))
        tk.Label(header, text=group.name, bg=_BG, fg=_FG, font=("Segoe UI", 14, "bold")).pack(side="left")
        RoundedButton(
            header, "Start All", command=lambda: self._start_group(group.name),
            bg=_BG, fill=_GREEN, outline=_GREEN, fg=_FG,
        ).pack(side="right")
        RoundedButton(
            header, "Delete Group", command=lambda: self._delete_group(group.name),
            bg=_BG, fill=_RED, outline=_RED, fg=_FG,
        ).pack(side="right", padx=(0, 6))

        templates = {template.key: template for template in self.templates}
        for member in group.members:
            card = tk.Frame(self.main, bg=_ROW_BG, highlightthickness=1, highlightbackground=_BORDER)
            card.pack(fill="x", padx=16, pady=(0, 8))
            template = templates.get(member.template_key)
            template_label = member.template_key
            if template is None:
                template_label += " (unavailable)"
            else:
                template_label += f" — {template.display_name}"
            tk.Label(
                card, text=f"{template_label}  :{member.port}", bg=_ROW_BG, fg=_FG,
                font=("Segoe UI", 10, "bold"), anchor="w",
            ).pack(fill="x", padx=10, pady=(8, 2))
            if member.extra_env:
                env_text = ", ".join(f"{key}={value}" for key, value in member.extra_env.items())
            else:
                env_text = "None"
            tk.Label(card, text=f"Environment: {env_text}", bg=_ROW_BG, fg=_DIM_FG, anchor="w").pack(
                fill="x", padx=10
            )
            tk.Label(
                card, text=f"Extra args: {member.extra_args or 'None'}", bg=_ROW_BG, fg=_DIM_FG, anchor="w",
            ).pack(fill="x", padx=10)
            tk.Label(
                card, text=f"Preset: {member.preset_name or 'None'}", bg=_ROW_BG, fg=_DIM_FG, anchor="w",
            ).pack(fill="x", padx=10, pady=(0, 8))

    def _render_server_detail(self, template: ServerTemplate | None) -> None:
        self._clear_main()
        if template is None:
            self._render_empty_state("Server", "Select a server.")
            return

        header = tk.Frame(self.main, bg=_BG)
        header.pack(fill="x", padx=16, pady=(16, 8))
        tk.Label(header, text=template.display_name, bg=_BG, fg=_FG, font=("Segoe UI", 14, "bold")).pack(side="left")

        if template.description:
            tk.Label(self.main, text=template.description, bg=_BG, fg=_DIM_FG, wraplength=560, justify="left").pack(
                anchor="w", padx=16, pady=(0, 8)
            )

        field_vars: dict[str, tk.StringVar] = {}
        port_var = tk.StringVar(value=str(template.default_port))
        args_var = tk.StringVar(value="")
        applied_preset_name: str | None = None

        def start() -> None:
            desired = int(port_var.get()) if port_var.get().isdigit() else template.default_port
            actual = _find_free_port(desired)
            extra_env = {name: var.get() for name, var in field_vars.items()}
            extra_args = args_var.get() if template.supports_args else ""
            instance = Instance(
                template, actual, extra_env, extra_args, preset_name=applied_preset_name,
            )
            self._wire_instance(instance)
            self.instances[instance.id] = instance
            if actual != desired:
                self.status.config(text=f"Port {desired} was taken - started {template.display_name} on {actual}.")
            else:
                self.status.config(text=f"Started {template.display_name} on port {actual}.")
            self._set_tab("instances")
            self._select_instance(instance.id)

        def add_preset() -> None:
            name = simpledialog.askstring(
                "Add as preset", f"Name for this {template.display_name} preset:", parent=self.root
            )
            if not name or not name.strip():
                return
            preset = Preset(
                name=name.strip(),
                port=int(port_var.get()) if port_var.get().isdigit() else template.default_port,
                env_vars={vname: var.get() for vname, var in field_vars.items()},
                args=args_var.get() if template.supports_args else "",
            )
            self.presets.setdefault(template.key, []).append(preset)
            _save_presets(self.presets)
            self.status.config(text=f"Saved preset {preset.name!r} for {template.display_name}.")
            self._render_server_detail(template)

        RoundedButton(
            header, "Start", command=start, bg=_BG, fill=_GREEN, outline=_GREEN, fg=_FG,
            font=("Segoe UI", 10, "bold"),
        ).pack(side="right")
        RoundedButton(
            header, "Add as Preset", command=add_preset, bg=_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        ).pack(side="right", padx=(0, 6))

        body = tk.Frame(self.main, bg=_BG)
        body.pack(fill="x", padx=16)

        self._build_field_row(body, "Port", port_var)
        for name, default_value in template.extra_env_vars.items():
            var = tk.StringVar(value=default_value)
            field_vars[name] = var
            self._build_field_row(body, name, var)
        if template.supports_args:
            self._build_field_row(body, "Extra args", args_var)
            hint = _EXTRA_ARGS_HINTS.get(template.key)
            if hint:
                tk.Label(
                    body, text=hint, bg=_BG, fg=_DIM_FG, font=("Segoe UI", 8), justify="left", anchor="w",
                ).pack(fill="x", padx=(18, 0), pady=(2, 0))

        def apply_preset(preset: Preset) -> None:
            nonlocal applied_preset_name
            port_var.set(str(preset.port))
            for vname, var in field_vars.items():
                if vname in preset.env_vars:
                    var.set(preset.env_vars[vname])
            if template.supports_args:
                args_var.set(preset.args)
            applied_preset_name = preset.name
            self.status.config(text=f"Applied preset {preset.name!r}.")

        def remove_preset(preset: Preset) -> None:
            self.presets.get(template.key, []).remove(preset)
            _save_presets(self.presets)
            self.status.config(text=f"Removed preset {preset.name!r}.")
            self._render_server_detail(template)

        presets = self.presets.get(template.key, [])
        if presets:
            tk.Label(body, text="PRESETS", bg=_BG, fg=_DIM_FG, font=("Segoe UI", 8, "bold")).pack(
                anchor="w", pady=(16, 4)
            )
            preset_row = tk.Frame(body, bg=_BG)
            preset_row.pack(fill="x")
            for preset in presets:
                PresetChip(
                    preset_row, preset.name,
                    on_apply=lambda p=preset: apply_preset(p), on_remove=lambda p=preset: remove_preset(p),
                    bg=_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
                ).pack(side="left", padx=(0, 8), pady=(6, 2))

        tk.Label(
            body, text=f"{template.venv_python.name}  -m {template.module}   (cwd: {template.working_dir})",
            bg=_BG, fg=_DIM_FG, font=("Segoe UI", 8), wraplength=560, justify="left",
        ).pack(anchor="w", pady=(16, 0))

    def _build_field_row(self, parent: tk.Frame, label: str, var: tk.StringVar) -> None:
        row = tk.Frame(parent, bg=_BG)
        row.pack(fill="x", pady=4)
        tk.Label(row, text=label, bg=_BG, fg=_DIM_FG, width=18, anchor="w").pack(side="left")
        tk.Entry(
            row, textvariable=var, bg=_FIELD_BG, fg=_FG, insertbackground=_FG, relief="flat",
            highlightthickness=1, highlightbackground=_BORDER, highlightcolor=_BORDER,
        ).pack(side="left", fill="x", expand=True, ipady=3)

    # ---- instances tab -----------------------------------------------------

    def _select_instance(self, instance_id: str) -> None:
        self.selected_instance_id = instance_id
        self._last_log_len = -1
        self._render_sidebar()
        self._render_instance_detail(instance_id)

    def _render_instance_detail(self, instance_id: str | None) -> None:
        self._clear_main()
        instance = self.instances.get(instance_id) if instance_id else None
        if instance is None:
            self._render_empty_state("Instance", "Select an instance.")
            return

        header = tk.Frame(self.main, bg=_BG)
        header.pack(fill="x", padx=16, pady=(16, 8))
        tk.Label(
            header, text=f"{instance.template.display_name}  :{instance.port}",
            bg=_BG, fg=_FG, font=("Segoe UI", 14, "bold"),
        ).pack(side="left")
        self._status_label = RoundedButton(
            header, instance.status, bg=_BG,
            fill=_STATUS_FILLS.get(instance.status, _ROW_BG),
            outline=_BORDER,
            fg=_FG if instance.status in _STATUS_FILLS else _DIM_FG,
        )
        self._status_label.pack(side="left", padx=(10, 0))

        if instance.preset_name:
            tk.Label(
                self.main, text=f"Preset: {instance.preset_name}", bg=_BG, fg=_DIM_FG,
            ).pack(anchor="w", padx=16, pady=(0, 8))

        RoundedButton(
            header, "Stop", command=lambda: self._stop_instance(instance.id),
            bg=_BG, fill=_RED, outline=_RED, fg=_FG,
        ).pack(side="right", padx=(6, 0))
        RoundedButton(
            header, "Restart", command=lambda: self._restart_instance(instance.id),
            bg=_BG, fill=_ROW_BG, outline=_BORDER, fg=_FG,
        ).pack(side="right")

        log_frame = tk.Frame(self.main, bg=_BG)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        text = tk.Text(
            log_frame, bg="#0d0d12", fg="#c9c9d4", insertbackground=_FG, relief="flat",
            font=("Consolas", 9), wrap="char", state="disabled",
        )
        scrollbar = tk.Scrollbar(log_frame, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        self._log_text = text
        self._refresh_log()

    def _refresh_log(self) -> None:
        """Periodic-poll refresh (from _tick) - reads whatever is current
        right now, since nothing dramatic is assumed to be mid-transition."""
        if self.selected_instance_id is None:
            return
        instance = self.instances.get(self.selected_instance_id)
        if instance is None:
            return
        self._update_status_badge(instance.status)
        self._refresh_log_text(instance)

    def _update_status_badge(self, status: str) -> None:
        if self._status_label is None:
            return
        fill = _STATUS_FILLS.get(status, _ROW_BG)
        fg = _FG if status in _STATUS_FILLS else _DIM_FG
        self._status_label.set(text=status, fill=fill, fg=fg)

    def _refresh_log_text(self, instance: "Instance") -> None:
        if self._log_text is None:
            return
        lines = list(instance.log_lines)
        if len(lines) == self._last_log_len:
            return
        self._last_log_len = len(lines)
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.insert("end", "\n".join(lines))
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    def _drain_status_queue(self) -> None:
        """Runs only on the main thread (self-rescheduling via root.after) -
        the single place that ever turns a queued (instance_id, status) pair
        from a background thread into an actual widget update."""
        try:
            while True:
                instance_id, status = self._status_queue.get_nowait()
                self._on_instance_status_change(instance_id, status)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_status_queue)

    def _on_instance_status_change(self, instance_id: str, status: str) -> None:
        """Handles one queued status update, with the status AS OF THE
        MOMENT IT CHANGED rather than re-read here - by the time the drain
        loop gets to it, self.status may already have moved past it (e.g. a
        fast stop->exited happened within the same tick), and re-reading
        would silently skip painting the transient state at all."""
        if self.active_tab != "instances" or self.selected_instance_id != instance_id:
            return
        self._update_status_badge(status)
        instance = self.instances.get(instance_id)
        if instance is not None:
            self._refresh_log_text(instance)

    def _wire_instance(self, instance: Instance) -> None:
        # A plain thread-safe queue.put() - never touches Tk from the
        # background thread that calls this. See _status_queue and
        # _drain_status_queue().
        instance.on_status_change = lambda status: self._status_queue.put((instance.id, status))

    def _adopt_running_instances(self) -> None:
        """Startup only, before the window is shown/interactive - a bounded
        handful of netstat calls (one per template) here is a one-time
        startup cost, not a recurring UI-thread block, so it's fine to run
        synchronously. What must NOT happen is checking these adopted
        instances' liveness on every _tick() afterwards - that's what each
        Instance's own background watcher thread is for (see
        Instance._start_liveness_watcher()), so is_alive() stays a cheap
        cached read from here on.

        Checks each template's default port, plus - if the previous session
        was closed with "keep running in the background" - whatever exact
        (template, port) pairs it left behind, even a custom/bumped port
        that wouldn't otherwise be found. A port nobody explicitly kept and
        that isn't a template's default stays invisible.

        Detection can be flaky right at startup (netstat/tasklist catching a
        process mid-bind), so this retries the same candidate ports until 3
        consecutive passes find nothing new, not just once."""
        templates_by_key = {t.key: t for t in self.templates}
        candidate_ports: dict[str, set[int]] = {t.key: {t.default_port} for t in self.templates}
        for template_key, port in _load_and_clear_kept_running():
            if template_key in candidate_ports:
                candidate_ports[template_key].add(port)

        adopted_ports: set[tuple[str, int]] = set()
        misses = 0
        first_pass = True
        while misses < 3:
            if not first_pass:
                time.sleep(0.3)
            first_pass = False
            found_this_pass = 0
            for template in self.templates:
                for port in candidate_ports[template.key]:
                    if (template.key, port) in adopted_ports:
                        continue
                    if self._try_adopt_port(template, port):
                        adopted_ports.add((template.key, port))
                        found_this_pass += 1
            misses = 0 if found_this_pass else misses + 1

    def _try_adopt_port(self, template: ServerTemplate, port: int) -> bool:
        """Adopts a running process on `port` as a new Instance, if one is
        there and isn't already tracked. Returns whether it adopted one."""
        if not _port_in_use(port):
            return False
        pid = _find_pid_on_port(port)
        if pid is None:
            return False
        instance = Instance(template, port, {}, "", adopted_pid=pid)
        self._wire_instance(instance)
        self.instances[instance.id] = instance
        return True

    def _refresh_active_tab(self) -> None:
        """Refresh button: on Servers, re-discover run.bat templates (new
        ones added on disk since launch). On Instances, re-scan default
        ports for background instances that startup adoption missed - e.g.
        one started just after this app launched."""
        if self.active_tab == "servers":
            selected_key = self.selected_template.key if self.selected_template else None
            self.templates = discover_templates()
            self.selected_template = next(
                (t for t in self.templates if t.key == selected_key), None
            )
            self.status.config(text="Refreshed server list.")
        else:
            tracked_ports = {
                (i.template.key, i.port) for i in self.instances.values() if i.is_alive()
            }
            found = 0
            for template in self.templates:
                port = template.default_port
                if (template.key, port) in tracked_ports:
                    continue
                if self._try_adopt_port(template, port):
                    found += 1
            self.status.config(
                text=f"Found {found} new instance(s)." if found else "No new background instances found."
            )
        self._render_sidebar()
        if self.active_tab == "servers":
            self._render_server_detail(self.selected_template)
        else:
            self._render_instance_detail(self.selected_instance_id)

    def _stop_instance(self, instance_id: str) -> None:
        instance = self.instances.get(instance_id)
        if instance is None:
            return
        if not messagebox.askyesno(
            "Stop server", f"Stop {instance.template.display_name} (port {instance.port})?", parent=self.root
        ):
            return
        self.status.config(text=f"Stopping {instance.template.display_name}...")
        threading.Thread(target=instance.stop, daemon=True).start()

    def _restart_instance(self, instance_id: str) -> None:
        instance = self.instances.get(instance_id)
        if instance is None:
            return
        if not messagebox.askyesno(
            "Restart server", f"Restart {instance.template.display_name} (port {instance.port})?", parent=self.root
        ):
            return
        self.status.config(text=f"Restarting {instance.template.display_name}...")
        threading.Thread(target=instance.restart, daemon=True).start()

    def _kill_all_instances(self) -> None:
        """Stops every tracked instance, including ones adopted at startup
        from a previous session (see _adopt_running_instances()). Runs on a
        background thread so the (possibly several) blocking taskkill calls
        never touch the UI thread - is_alive() here is always a cheap cached
        read (Popen.poll() or Instance._adopted_alive), never a blocking
        check, so building `running` itself is instant too."""
        running = [i for i in self.instances.values() if i.is_alive()]
        if not running:
            messagebox.showinfo("Kill Instances", "No running instances.", parent=self.root)
            return
        if not messagebox.askyesno(
            "Kill Instances",
            f"Kill all {len(running)} running instance(s)? This cannot be undone.",
            parent=self.root,
        ):
            return
        self.status.config(text=f"Killing {len(running)} instance(s)...")

        def kill_all() -> None:
            for instance in running:
                instance.stop()

        threading.Thread(target=kill_all, daemon=True).start()

    def _restart_all_instances(self) -> None:
        """Restarts every running instance in parallel (one thread each -
        Instance.restart() blocks while it waits for the old process to
        exit, so serial restarts would add up)."""
        running = [i for i in self.instances.values() if i.is_alive()]
        if not running:
            messagebox.showinfo("Restart All", "No running instances.", parent=self.root)
            return
        if not messagebox.askyesno(
            "Restart All",
            f"Restart all {len(running)} running instance(s)?",
            parent=self.root,
        ):
            return
        self.status.config(text=f"Restarting {len(running)} instance(s)...")
        for instance in running:
            threading.Thread(target=instance.restart, daemon=True).start()

    def _clear_closed_instances(self) -> None:
        """Forgets only instances whose processes have already stopped."""
        closed_ids = [instance_id for instance_id, instance in self.instances.items() if not instance.is_alive()]
        for instance_id in closed_ids:
            del self.instances[instance_id]
        if self.selected_instance_id not in self.instances:
            self.selected_instance_id = None
        self._render_sidebar()
        self._render_instance_detail(self.selected_instance_id)
        count = len(closed_ids)
        self.status.config(
            text=f"Cleared {count} closed instance{'s' if count != 1 else ''}."
            if count else "No closed instances to clear."
        )

    # ---- periodic refresh -------------------------------------------------

    def _tick(self) -> None:
        for instance_id, card in self.instance_dots.items():
            instance = self.instances.get(instance_id)
            if instance is not None:
                card.set_dot_color(_GREEN if instance.is_alive() else _DIM_FG)
        if self.active_tab == "instances" and self.selected_instance_id:
            self._refresh_log()
        self.root.after(_POLL_MS, self._tick)

    # ---- lifecycle ----------------------------------------------------

    def _on_close(self) -> None:
        """Closing the window asks what to do with instances it launched,
        when any are still running: stop them, or leave them running in the
        background - a spawned server is a real independent OS process that
        outlives this window either way, so "leave running" needs to save
        which (template, port) pairs to re-adopt next launch (see
        _adopt_running_instances()), or they'd be invisible orphans."""
        running = [i for i in self.instances.values() if i.is_alive()]
        if not running:
            self.root.destroy()
            return
        choice = messagebox.askyesnocancel(
            "Quit Server Launcher",
            f"{len(running)} server instance(s) still running.\n\n"
            "Yes - stop them and quit.\n"
            "No - keep them running in the background (picked back up next time this app opens).\n"
            "Cancel - don't quit.",
            parent=self.root,
        )
        if choice is None:
            return
        if choice:
            for instance in running:
                instance.stop()
        else:
            _save_kept_running([self._detach_for_background(i) for i in running])
        self.root.destroy()

    def _detach_for_background(self, instance: Instance) -> tuple[str, int]:
        """A self-spawned instance's stdout pipe is read by a thread in THIS
        process - confirmed by testing that this thread reliably takes the
        child down with it at interpreter shutdown (torn down mid-syscall on
        the pipe), even though the child is otherwise an independent OS
        process. So "keep running in the background" isn't just leaving it
        alone: for a self-spawned one, swap it for a freshly-spawned
        replacement with no pipe tied to us at all (losing its log history -
        nothing would be left to read it anyway), then hand that one's port
        back to be saved. An already-adopted instance has no pipe in this
        process to begin with and needs no swap."""
        if instance.process is None:
            return instance.template.key, instance.port
        _kill_pid_tree(instance.process.pid)
        deadline = time.time() + _RESTART_WAIT_SECONDS
        while time.time() < deadline and _port_in_use(instance.port):
            time.sleep(0.2)
        _spawn_detached(instance.template, instance.port, instance.extra_env, instance.extra_args)
        return instance.template.key, instance.port


def _hide_console_window() -> None:
    """Hides the console window this process was launched from (running
    via `python server_launcher.py` from a shell opens one) once the GUI
    is up - it serves no purpose alongside the Tk window and just looks
    like a leftover terminal. Hidden, not closed: closing the console
    that owns this process's own stdio can take the process down with
    it on Windows. No-op off Windows or if there's no console to hide
    (e.g. launched via pythonw.exe already)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:  # noqa: BLE001 - cosmetic only, never block startup over this
        pass


def main() -> None:
    _hide_console_window()
    root = tk.Tk()
    LauncherWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
