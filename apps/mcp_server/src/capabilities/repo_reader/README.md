# capabilities/repo_reader/

Read git history, diffs and code of the workspace projects, read-only - four tools.

## Tools

| Tool | Purpose | Connection |
| --- | --- | --- |
| `tool_repo_listRepos` | List the git repos in the workspace. | Local git |
| `tool_repo_log` | Newest commits with changed files. | Local git |
| `tool_repo_diff` | Changes between two points or the working tree. | Local git |
| `tool_repo_grep` | Find plain text in tracked files. | Local git |

## Slash commands

| Tool | Slash command | Parameters |
| --- | --- | --- |
| `tool_repo_listRepos` | `/repo list` | <ul><li>none.</li></ul> |
| `tool_repo_log` | `/repo log` | <ul><li>`repo` - required. Repo path relative to the workspace.</li><li>`max_count` - optional, default `20`. 1 to 50.</li><li>`path` - optional. A file or folder.</li><li>`author` - optional. Author text.</li><li>`since` - optional. Date or age.</li></ul> |
| `tool_repo_diff` | `/repo diff` | <ul><li>`repo` - required. Repo path.</li><li>`base` - optional, default `HEAD`. Compare from.</li><li>`target` - optional. Compare to; empty is the working tree.</li><li>`path` - optional. A file or folder.</li><li>`stat_only` - optional, default `true`. Files only, or the full diff.</li></ul> |
| `tool_repo_grep` | `/repo grep` | <ul><li>`repo` - required. Repo path.</li><li>`pattern` - required. Plain text, case-insensitive.</li><li>`path` - optional. A file or folder.</li><li>`max_matches` - optional, default `50`. Per file, 1 to 100.</li></ul> |

## Typical workflow

| Sequence | Tool | Explanation |
| --- | --- | --- |
| 1 | `tool_repo_listRepos` | Find the exact repo path. |
| 2 | `tool_repo_log` / `tool_repo_grep` | See what changed recently, or find code. |
| 3 | `tool_repo_diff` | Look at one change in detail. |

## Configuration

`MCP_WORKSPACE_DIR` in `.env`: the folder that holds the project repos. Default `../../../..` (the `Programming`
folder), relative to `apps/mcp_server/`. Needs `git` on the server's PATH.

Safety: only fixed read-only git subcommands run, with no shell. A revision must be a plain branch, tag or commit
name; paths go after `--` and are checked by `services/confined_paths.py` (inside the repo, no `..`); patterns are
fixed strings. `.env*`, `secrets/`, `.secrets/`, key files and private keys are excluded from every command by
pathspec, and `grep` searches tracked files only. Output is capped at 24 KB and fenced as data. A command stops
after 20 seconds.

Toggle: `"repo"` in `configs/config_capabilities.json`.
