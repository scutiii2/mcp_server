# capabilities/host_health/

CPU, memory, disk, and uptime for a configured SSH host - exposed both
as a tool (`get_host_health_tool`, for a model) and a resource
(`host://health/{name}`, for a client reading a URI directly). Same
domain logic underneath (`resources/host_health/domain.py`); this
folder's `tool.py` wraps it for the model-facing case.

**Reads:** `../../../configs/config_hosts.json` (the host inventory) and,
through `infra/ssh.py`, `../../../secrets/secret_ssh.env` (host-key
policy and any password-authenticated host's `*_SSH_PASSWORD`).

**Owns no data or secrets of its own** - it only reads, over SSH, and
returns a report; nothing it produces is persisted.

**Toggle:** `"host_health"` in `../../../configs/config_capabilities.json`.
Disabling it removes both the tool and the resource.
