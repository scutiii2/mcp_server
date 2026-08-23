"""Registered Crafty Controller worlds: start, stop, restart, list,
register, send a console command, and check status.

Unlike ``server_manager`` (Docker containers on this host) or
``host_health`` (this host's own machines), what this capability
controls isn't fixed by the deployment - worlds are registered at
runtime via ``crafty_world_register_tool``, against whichever Crafty
Controller instance(s) the caller names.
"""
