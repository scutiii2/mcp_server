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

## Standalone exe

```
server_launcher\build.bat
```

Builds `dist\scuti_server_launcher.exe` with PyInstaller (one file, no console
window). The exe carries its own Python, so the launcher itself runs on a
machine without Python. The projects it starts still need Python (to build a
venv) or Node, per project; see the warnings below. Needs Python 3.11+ on the
build machine only. Run it from a double-click; first build downloads
PyInstaller into `.venv_launcher`. Settings and saved servers live in the data
folder, not next to the exe (see below).

## What it does

Lists only the projects you add with the Servers tab's **Add** button; nothing
is scanned at startup. A project can be added three ways:

1. **Its `run.bat`**: the launcher reads the venv-folder and `py -m <module>`
   lines (or `npm run <script>`), `set` lines, and the `REM` lines below.
2. **Its `run.srvlnchr`**: a JSON file made for this launcher (below). If a
   folder has both, `run.srvlnchr` wins.
3. **Manual setup**: for a project with neither file. Pick one folder and type
   the fields into a form.

Whichever way, the launcher saves its own copy of the spec in
`projects/<folder name>/run.srvlnchr` in the data folder (with the project path and where it
came from), and lists servers from those copies only. A project's own file is
re-read on each start and refresh, so edits to it are picked up; if the file is
erased or unreadable, the saved copy keeps the server working. A manual spec
has no file to follow. The project folder and its venv must still exist.

The launcher runs each project directly as
`<project>/.venv_<id>/Scripts/python.exe -m <module>` (or `npm run <script>`).
That gives a real `Popen` handle with piped stdout, which is what makes the
in-app log viewer and programmatic stop/restart possible. A missing venv is
bootstrapped the same way the bat does (`py -m venv`, `pip install -e .[dev]`).

`run.srvlnchr` (every key optional except `module`, and `venv` for python):

```json
{
  "label": "PDF Merger",
  "description": "Merges PDFs",
  "runtime": "python",
  "venv": "pdf_merger",
  "module": "src.run",
  "port_env_var": "PDF_MERGER_PORT",
  "port": 8040,
  "env": {"MODE": "dev"},
  "supports_args": false
}
```

`"runtime": "node"` runs `npm run <module>` and needs a `package.json`.
`"skip": true` leaves the project out. In a `run.bat`, `REM LABEL:` /
`REM DESCRIPTION:` set the display name/blurb and `REM LAUNCHER: skip` leaves
it out (chat_cli uses it: it is an interactive terminal program, not a
server). This launcher's own folder is never listed.

Python and node are checked per project, not for the whole app. A python project
with no venv yet needs Python 3.11+ to build it; a node project needs `node` and
`npm`. If the one it needs is missing, its page shows a red warning (install it
and put it in the environment variables), Start is refused, and Start all on a
group names it. Each candidate (`py -3`, `python`, `python3`) is run to check
its version, so the Microsoft Store's stub `python.exe` is not taken for Python.
Found once per run: install, then close and reopen the launcher.

Every file the launcher creates at run time (groups, presets, the saved server
specs, the kept-running handoff) lives in one data folder, by default
`%APPDATA%\scuti_server_launcher`. To use another folder, set the first of
these that applies: `--data-dir <path>` on the command line, the
`SCUTI_SERVER_LAUNCHER_DATA` environment variable, or a `data_location.txt`
whose first line is the path, kept in the default folder. On first start,
`groups.json` and `presets.json` from the old in-tree `.data/` are copied over
if the new folder does not have them (the old folder is left alone).

Sidebar tabs:
- **Servers**: every added project; flags (port, `set NAME=value` env
  lines, Extra args when the bat forwards `%*`), saved Presets, Start. A taken
  port auto-bumps to the next free one.
  **Add** opens a dialog where you list any number of projects: `Add folder…`
  per project (checked as you go), `Manual setup…` for one without a run file,
  then `Add all`. **Remove** forgets the selected one (deletes the launcher's
  copy); project files are never touched.
- **Agent projects** (a bat that runs `src.supervisor` next to an `agents/`
  folder, i.e. ai_agent): the Servers page shows the agent files read-only
  (id, port, provider and model, entry agent, disabled ones dimmed) instead of
  flags and presets. The entry agent's port is the project's port, in groups
  too. Start never bumps it: if that port is taken, Start is refused, so a
  second supervisor never fights the first for the agents' ports. Edit
  `agents/<id>.json` to change agents; the launcher never writes them.
- **Instances**: everything started (or adopted) by this tool; live log tail,
  Stop/Restart, Kill/Restart all, Clear closed, Create group.
- **Groups**: saved sets of instance recipes (template, port, env, args,
  preset), shown as one card per member; Start all.
  Edit opens an inline editor: change each member's port, env vars, extra
  args or preset, remove members, or add a server from the template list.
  Save is refused for a bad port, a port used twice, or an empty group; Cancel
  discards the changes. Agent projects keep their entry-agent port, and a
  member whose server is no longer in the list can only be removed.

The sidebar list and the group member list scroll when they overflow; the
scrollbar appears only then.

## Look

Dark only, in ember_web's dark tokens (`apps/Ember/ember_web/src/style.css`): the
colors and the 4/8/12 px radius scale live in `src/theme.py`. Ember orange
marks the active tab, the selected row and the one primary button per view
(Start, Start all); danger actions (Stop, Kill, Delete group) are outlined in
the danger color; status badges are tinted chips with a text label. Tk has no
border-radius, so `src/widgets.py` draws rounded shapes on canvases. Change a
color or radius in `theme.py`, not at the call site.

Limitation, by design: a server started outside this tool has no `Popen`
handle, so it only appears under Instances if adopted (found on a template's
default port, or a port kept via "keep running in background" on close).

## Layout

| Path | Contents |
|---|---|
| `src/run.py` | Entry point (`py -m src.run`); `launcher.py` is the top-level script PyInstaller builds from |
| `build.bat` | Builds the standalone exe |
| `src/window.py` | `LauncherWindow`: tabs, sidebar, detail panes, lifecycle |
| `src/instance.py` | `Instance`: launch, log capture, stop/restart, adoption |
| `src/processes.py` | Port/PID helpers, venv bootstrap, spawn |
| `src/add_dialog.py` | `AddServersDialog` (collect several projects, then add them at once), `ManualSetupDialog` |
| `src/runtimes.py` | Finds python / node on PATH, words the per-project warning |
| `src/specs.py` | `run.srvlnchr` JSON: read, validate, write; manual-form validation |
| `src/discovery.py` | Reads a folder's `run.srvlnchr` / `run.bat` into a spec; builds templates from specs |
| `src/agent_files.py` | Read-only agent files of a supervisor project; entry port, start refusal |
| `src/group_editor.py` | `GroupEditor`: inline edit/add/remove of a group's members |
| `src/storage.py` | Load/save groups, presets, saved server specs, kept-running handoff |
| `src/models.py` | `ServerTemplate`, `AgentInfo`, `Preset`, `GroupMember`, `ServerGroup` |
| `src/widgets.py`, `src/theme.py` | Rounded hover widgets, member card, panel, scroll frame, dark scrollbar; ember colors and radius scale |
| `src/config.py` | Paths and data folder resolution, run.bat regexes, timing constants |
| `src/assets/` | Empty-state image |
| data folder | `groups.json`, `presets.json`, `projects/<name>/run.srvlnchr`, `kept_running.json`, `data_location.txt` (see above; never in the repo) |
| `tests/` | pytest suite |

No `configs/` or `secrets/`: the launcher has neither.
