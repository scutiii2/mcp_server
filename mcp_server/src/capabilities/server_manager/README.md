# capabilities/server_manager/

Start, stop, restart, and list the Docker containers on this host -
four tools (`start_app_tool`, `stop_app_tool`, `restart_app_tool`,
`list_apps_tool`), also invocable as `/server_manager start|stop|restart|list`.

**Reads:** nothing under `../../configs/` - there's no per-deployment
config here, just whatever Docker daemon `docker.from_env()` finds.

**Requires:** the host's Docker socket reachable from this process. The
intended deployment (`../../../zima_host.yaml`) runs this server as its
own container on the same ZimaOS box as the apps it manages, with
`/var/run/docker.sock:/var/run/docker.sock` bind-mounted in - so it
controls sibling containers on the same daemon, not a remote one.
Without that mount, every tool here fails with a message saying so; the
rest of the server is unaffected (see `domain.py`'s docstring for why).

**Owns no data or secrets of its own** - it only starts/stops/restarts
containers that already exist and reads their state back.

**Toggle:** `"server_manager"` in `../../configs/config_capabilities.json`.
Disabling it removes all four tools.
