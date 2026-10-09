"""Real-widget checks for overflowing server settings in a small window."""

from pathlib import Path
import sys
import tkinter as tk
from types import SimpleNamespace

import pytest

from src.models import ServerTemplate
from src.widgets import RoundedButton, ScrollableFrame
from src.window import LauncherWindow


@pytest.fixture
def launcher():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.geometry("850x400")
    window = object.__new__(LauncherWindow)
    window.root = root
    window.main = tk.Frame(root)
    window.main.pack(fill="both", expand=True)
    window.status = tk.Label(root)
    window.presets = {}
    try:
        yield window
    finally:
        root.destroy()


def template(fields):
    return ServerTemplate(
        key="test", display_name="Test server", description="Server settings",
        working_dir=Path.cwd(), venv_python=Path(sys.executable), module="src.run",
        port_env_var="PORT", default_port=8000,
        extra_env_vars={f"SETTING_{i}": str(i) for i in range(fields)}, supports_args=True,
    )


def test_overflowing_server_detail_scrolls_and_keeps_start_visible(launcher):
    launcher._render_server_detail(template(24))
    launcher.root.update()
    scroll = next((child for child in launcher.main.winfo_children() if isinstance(child, ScrollableFrame)), None)
    assert scroll is not None, "Server settings need a scrolling container"
    assert scroll._scrollbar.winfo_ismapped()
    assert scroll._canvas.yview()[1] < 1
    start = next(
        button for child in launcher.main.winfo_children() for button in child.winfo_children()
        if isinstance(button, RoundedButton) and button.text == "Start"
    )
    header_y = start.winfo_rooty()
    scroll._on_wheel(SimpleNamespace(delta=-120))
    launcher.root.update()
    assert scroll._canvas.yview()[0] > 0
    scroll._canvas.yview_moveto(1)
    launcher.root.update()
    assert scroll._canvas.yview()[1] == 1
    command_panel = scroll.body.winfo_children()[-1]
    assert command_panel.winfo_rooty() >= scroll._canvas.winfo_rooty()
    assert command_panel.winfo_rooty() + command_panel.winfo_height() <= scroll._canvas.winfo_rooty() + scroll._canvas.winfo_height()
    assert start.winfo_ismapped()
    assert start.winfo_rooty() == header_y


def test_switching_to_short_server_hides_scrollbar_and_resets_position(launcher):
    launcher._render_server_detail(template(24))
    launcher.root.update()
    launcher._render_server_detail(template(0))
    launcher.root.update()
    scroll = next((child for child in launcher.main.winfo_children() if isinstance(child, ScrollableFrame)), None)
    assert scroll is not None, "Server settings need a scrolling container"
    assert not scroll._scrollbar.winfo_ismapped()
    assert scroll._canvas.yview() == (0, 1)
