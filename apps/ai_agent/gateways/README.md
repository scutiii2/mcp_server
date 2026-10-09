# gateways/

One local gateway preset per `gateways/<provider>/<gateway>.json`, beside
`agents/`. The directory name is the provider protocol (`anthropic` or
`openai`); the filename without `.json` is the gateway id used by an agent's
`llm.gateway`. A gateway supporting both protocols can have a file in each
provider directory. Laya's `local` gateway remains built in.

Each file contains the gateway block directly, without provider or gateway
wrapper keys. For example, `anthropic/claude.json`:

```json
{
  "label": "Claude",
  "api_key": "{CLAUDE_API_KEY}",
  "model": "claude-sonnet-5",
  "models": {
    "light": {"id": "claude-haiku-4-5", "use_for": "quick tasks"},
    "standard": {"id": "claude-sonnet-5", "use_for": "most tasks"}
  }
}
```

Use `{ENV_VAR_NAME}` placeholders for credentials; the actual values belong
in `../.env`. Files can also specify gateway-specific fields such as
`base_url`, `auth_token`, `azure_endpoint`, or `aws_region`. Optional `models`
defines the `light`, `standard`, and `heavy` tiers. Agent files keep their
existing `llm.provider` and `llm.gateway` values.

On first read, `src/llm/llm_config.py` splits an existing
`../configs/config_gateways.json` into individual files, preserving custom
gateways and leaving existing individual files untouched. It validates the
complete legacy configuration before publishing files, and retains the old
file as an unused rollback backup. Existing installations keep their gateway
set; migration does not add the example gateways.

With no legacy configuration, first read seeds the committed `.json.example`
files into local `.json` files. Initialization writes `.initialized` only
after all files are published. Keep this marker: it prevents later startups
from rereading the backup or recreating gateways you deliberately removed.
To add a gateway after initialization, create its `.json` file or copy an
example yourself. Local `.json` files and the marker are gitignored.

The gateway loader and admin catalog share these definitions and cache them
for the process lifetime. Restart the agent processes and supervisor after
editing gateway files. For rollback, use the previous code with the retained
legacy file; copy any subsequent gateway changes back into that file first.
