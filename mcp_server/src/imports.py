"""Imports every built-in capability onto `mcp`, then applies each
one's enabled/disabled state from config_capabilities.json.

Split out of run.py so the list of capability imports - which grows by
one block every time a new capability is added, per
capabilities/README.md's "Add a new capability" step 7 - doesn't crowd
out run.py's actual job of assembling and serving the app.

A plain module-level side-effecting import, not a function run.py
calls: every `with capability_registry.capturing(mcp, "<name>"):
from src.capabilities.<name> import tool` block below needs that
`from` import to actually execute for capturing() to capture anything,
and Python only runs a module's top level once no matter how many times
it's imported - so `import src.imports` (run.py does this, once, at
startup) is what makes this run, not a call this module exposes.
"""

from __future__ import annotations

from src.config import settings
from src.infra import capability_metadata, capability_registry
from src.infra.app_config import capability_enabled, load_capabilities_config
from src.server import mcp

_capabilities_config = load_capabilities_config(settings.capabilities_config_path)

# Import order = the order tools/resources appear in their respective
# list calls. Add each new capability's tool/resource module here as it's
# built, following the pattern in capabilities/<name>/ (contract.py /
# domain.py / tool.py) described in the README's "Adding a new tool"
# section - and add a toggle entry to config_capabilities.json /
# config_capabilities.json.example.
#
# Every capability imports unconditionally now, even a disabled one -
# capability_registry.capturing() needs the import to actually happen so
# it can capture what got registered, which is what makes toggling a
# capability back on later possible without re-importing (Python caches
# modules, so a second import wouldn't re-run the @mcp.tool() decorators
# anyway). Disabled state is applied immediately below, via the same
# registry a live PATCH /capabilities/{name} request uses later - see
# capability_routes.py and infra/capability_registry.py.
#
# host_health appears twice on purpose: the resource serves clients that
# read a URI, the capability serves models that can only see tools. Same
# domain logic underneath, same toggle entry (and the same `capturing`
# block) governs both - see capabilities/host_health/domain.py.
with capability_registry.capturing(mcp, "host_health"):
    from src.capabilities.host_health import tool as host_health_tool  # noqa: E402,F401
    from src.resources.host_health import resource as host_health_resource  # noqa: E402,F401

with capability_registry.capturing(mcp, "otp"):
    from src.capabilities.otp import tool as otp_tool  # noqa: E402,F401

with capability_registry.capturing(mcp, "server_manager"):
    from src.capabilities.server_manager import tool as server_manager_tool  # noqa: E402,F401

# Every name capturing() used above must match its capabilities/<name>/
# folder exactly: commands.py's @command decorator independently infers
# the same id from the decorated function's module path
# (src.capabilities.host_health.tool -> "host_health"), and
# config_capabilities.json's keys are these same folder names too. All
# three have to agree on one canonical id, or a capability's config-file
# toggle silently stops matching what got registered here. A *shorter*
# id for chat_app's slash commands to type belongs in that capability's
# own __init__.py as COMMAND_ID (see infra/capability_metadata.py) - not
# here.
capability_metadata.validate_command_ids(capability_registry.names())

for _name in capability_registry.names():
    if not capability_enabled(_capabilities_config, _name):
        capability_registry.set_enabled(mcp, _name, False)
