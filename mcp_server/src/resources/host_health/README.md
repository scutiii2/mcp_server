# resources/host_health/

Exposes the same host-health data as `capabilities/host_health/`, for a
client that already knows which host it wants and can read
`host://health/{name}` directly instead of making a tool call. This
folder owns the real logic (`domain.py`'s `collect()`/`format_report()`,
`contract.py`'s `HostHealth`/`DiskUsage` models); the capability imports
from here, not the other way around - see
`capabilities/host_health/domain.py`'s docstring.

**Reads:** `../../configs/config_hosts.json` and, through `infra/ssh.py`,
`../../secrets/secret_ssh.env`.

**Toggle:** shares the `"host_health"` entry in
`../../configs/config_capabilities.json` with the capability - disabling
it removes both the tool and this resource.
