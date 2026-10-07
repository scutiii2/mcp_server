# configs/

Structured settings for the agents, most gitignored (deployment-specific tuning).

## Configuration files

- **`config_gateways.json`** (gitignored) - LLM provider and gateway definitions.
  Loaded by `src/llm/llm_config.py`'s `gateway()`.
  A block may also have `models`: up to three strength tiers (`light`,
  `standard`, `heavy`), each `{id, use_for}`, read by `tiers()`. `model`
  stays the default; an agent file's `llm.min_tier`/`llm.max_tier` cap which
  tiers it may run on, and an orchestrator picks one per delegated task from
  the `use_for` text (`src/llm/model_tiers.py`).
  See `config_gateways.json.example` for a template with tiers.

- **`config_limits.json`** (gitignored) - Output token limits per model;
  an agent file can lower its own.

- **`prompts.json`** (gitignored) - Agent roles and shared tool-use instructions.
  Each role has a `label` and `persona` (system-prompt text).
  Loaded by `src/llm/agent_roles.py`.

- **`config_tool_selection.json`** (gitignored) - Laya tool shortlist tuning
  (not used by cloud agents).

- **`config_gateways.json.example`** (committed) - Template for
  `config_gateways.json`, with tiers defined for the Claude gateway.

- **`config_limits.json.example`**, **`config_tool_selection.json.example`**,
  **`prompts.json.example`** (committed) - Templates for the real config files.

