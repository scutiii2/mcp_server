# server_launcher

Tkinter desktop launcher for this repo's dev servers. Stdlib only (no
Flask/web server: it only spawns, inspects and kills local processes and
streams their stdout, which a browser tab cannot do).

## Run

```
server_launcher\run.bat
```

First run creates `.venv_launcher` and installs the project editable.
Tests: `cd server_launcher && .venv_launcher\Scripts\python -m pytest`.

## What it does

Autodetects every `<project>/run.bat` at the repo root (`mcp_server`,
`chat_app`, `catalog_service`, `ai_agent`) by parsing its venv-folder and
`py -m <module>` lines, and runs each directly as
`<project>/.venv_<id>/Scripts/python.exe -m <module>`. That gives a real
`Popen` handle with piped stdout, which is what makes the in-app log viewer
and programmatic stop/restart possible. A missing venv is bootstrapped the
same way the bat does (`py -m venv`, `pip install -e .[dev]`).
`REM LABEL:` / `REM DESCRIPTION:` lines in a bat set its display name/blurb.
This launcher's own folder is skipped by discovery.

Sidebar tabs:
- **Servers**: every detected template; flags (port, `set NAME=value` env
  lines, Extra args when the bat forwards `%*`), saved Presets, Start. A taken
  port auto-bumps to the next free one.
- **Instances**: everything started (or adopted) by this tool; live log tail,
  Stop/Restart, Kill/Restart All, Clear Closed, Create Group.
- **Groups**: saved sets of instance recipes (template, port, env, args,
  preset); Start All.

Limitation, by design: a server started outside this tool has no `Popen`
handle, so it only appears under Instances if adopted (found on a template's
default port, or a port kept via "keep running in background" on close).

## Layout

| Path | Contents |
|---|---|
| `src/run.py` | Entry point (`py -m src.run`) |
| `src/window.py` | `LauncherWindow`: tabs, sidebar, detail panes, lifecycle |
| `src/instance.py` | `Instance`: launch, log capture, stop/restart, adoption |
| `src/processes.py` | Port/PID helpers, venv bootstrap, spawn |
| `src/discovery.py` | `discover_templates()` from run.bat files |
| `src/storage.py` | Load/save groups, presets, kept-running handoff |
| `src/models.py` | `ServerTemplate`, `Preset`, `GroupMember`, `ServerGroup` |
| `src/widgets.py`, `src/theme.py` | Rounded hover widgets, colors |
| `src/config.py` | Paths, run.bat regexes, timing constants |
| `src/assets/` | Empty-state image |
| `data/` | `groups.json` (tracked); `presets.json`, `kept_running.json` (gitignored, per-machine) |
| `tests/` | pytest suite |

No `configs/` or `secrets/`: the launcher has neither.
