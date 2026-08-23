"""Capabilities - one folder per tool, self-contained.

Each subfolder holds everything specific to that capability:

  - ``contract.py``  Pydantic request/result models
  - ``domain.py``    the real logic - typed in, typed out, imports only
                      ``infra/``, never ``mcp`` or ``flask``. This is what
                      you unit test.
  - ``tool.py``       a few lines: load config, call the domain function,
                      return its result. ``@mcp.tool()`` appears here and
                      nowhere else.

Shared infrastructure (``infra/ssh.py``, ``infra/email.py``,
``infra/app_config.py``, ``infra/pending_requests.py``) stays one level
up, at ``mcp_server/infra/`` - every capability reuses the same clients
and config loader rather than each folder inventing its own.

Add a new capability by:
  1. mkdir capabilities/<name>/ with an __init__.py
  2. capabilities/<name>/contract.py
  3. capabilities/<name>/domain.py
  4. capabilities/<name>/tool.py
  5. capabilities/<name>/README.md - what it reads, what (if anything)
     it owns under its own data/ or secrets/, how to toggle it off
  6. Add a toggle entry to ../configs/config_capabilities.json and
     config_capabilities.json.example
  7. Gate `from mcp_server.capabilities.<name> import tool` behind
     `capability_enabled(...)` in run.py, following host_health/otp

``otp/`` is the worked example: two tools, a domain module that imports
only ``infra/``, and a contract whose shape carries the security property
(the passcode is deliberately absent from the result model).

A third pattern, alongside "capability" and "resource" above, lives at
``infra/extensions.py``: proxied external tools, connected out to other
MCP servers as a client and re-exposed here under a namespaced name,
rather than written by hand in this repo at all.
"""
