# agents/

Each tracked `<id>.json` defines one agent. These files are the source of
truth for the supervisor and admin UI: edits in either place produce Git
changes. There are no template copies or startup seeding.

The committed roster includes Ember as its enabled entry agent and the
existing specialists. Every enabled agent needs a distinct port, and exactly
one enabled agent must set `entry: true`. Add an agent by creating a new file
or copying a definition to a new id and adjusting its port and role. Disable
an agent with `enabled: false`.

An agent's `llm.provider` and `llm.gateway` refer to
`../gateways/<provider>/<gateway>.json`; Laya's `local` gateway is built in.
Keep credentials in `../.env`. Ports, URLs, persona text and instructions in
these definitions are repository content, so review them before committing.
See `../README.md` for the field descriptions and examples.

The supervisor watches this directory and reconciles validated changes.
`.data/agent_definitions.json` is its generated summary of all configured
agents; `.data/agent_registry.json` records registered running instances.
Both remain ignored runtime state, along with usage logs. Temporary admin
write files are ignored too.
