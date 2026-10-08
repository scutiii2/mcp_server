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
`catalog_service`, `ai_agent`) by parsing its venv-folder and
`py -m <module>` lines, and runs each directly as
`<project>/.venv_<id>/Scripts/python.exe -m <module>`. That gives a real
`Popen` handle with piped stdout, which is what makes the in-app log viewer
and programmatic stop/restart possible. A missing venv is bootstrapped the
same way the bat does (`py -m venv`, `pip install -e .[dev]`).
`REM LABEL:` / `REM DESCRIPTION:` lines in a bat set its display name/blurb.
A `REM LAUNCHER: skip` line leaves the project out (chat_cli uses it: it is an
interactive terminal program, not a server).
This launcher's own folder is skipped by discovery.

Sidebar tabs:
- **Servers**: every detected template; flags (port, `set NAME=value` env
  lines, Extra args when the bat forwards `%*`), saved Presets, Start. A taken
  port auto-bumps to the next free one.
  **Add** picks a project folder with a launchable `run.bat` and lists it;
  **Remove** drops the selected server from the list (a folder added by hand
  is forgotten, a detected one is hidden; Add its folder to bring it back).
  Project files are never touched. Both are saved in `data/servers.json`
  (gitignored, per machine).
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
  member whose template is no longer detected can only be removed.

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
| `src/run.py` | Entry point (`py -m src.run`) |
| `src/window.py` | `LauncherWindow`: tabs, sidebar, detail panes, lifecycle |
| `src/instance.py` | `Instance`: launch, log capture, stop/restart, adoption |
| `src/processes.py` | Port/PID helpers, venv bootstrap, spawn |
| `src/discovery.py` | `discover_templates()` from run.bat files |
| `src/agent_files.py` | Read-only agent files of a supervisor project; entry port, start refusal |
| `src/group_editor.py` | `GroupEditor`: inline edit/add/remove of a group's members |
| `src/storage.py` | Load/save groups, presets, added/hidden servers, kept-running handoff |
| `src/models.py` | `ServerTemplate`, `AgentInfo`, `Preset`, `GroupMember`, `ServerGroup` |
| `src/widgets.py`, `src/theme.py` | Rounded hover widgets, member card, panel, scroll frame, dark scrollbar; ember colors and radius scale |
| `src/config.py` | Paths, run.bat regexes, timing constants |
| `src/assets/` | Empty-state image |
| `data/` | `groups.json` (tracked); `presets.json`, `servers.json`, `kept_running.json` (gitignored, per-machine) |
| `tests/` | pytest suite |

No `configs/` or `secrets/`: the launcher has neither.
