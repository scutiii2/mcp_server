"""Server manager: start, stop, restart and list the Docker containers on
this host."""

from src.services import capability_meta

META = capability_meta.register(folder="server_manager", id="server", label="Server Manager")
