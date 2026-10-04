"""Custom rounded Tk widgets with the hover/press sweep animation."""

from __future__ import annotations

import time
import tkinter as tk
from typing import Callable

from .theme import _HOVER_DURATION_MS, _HOVER_LIGHTEN, _RADIUS, _ease_in_out, _lighten


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
