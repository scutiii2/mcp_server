"""Capabilities - one folder per tool, self-contained.

Each subfolder (``control/``, and eventually ``monitoring/``, ``jobs/``,
``kernel/``, ``rename/``, ``conversion/``, ``provisioning/``) holds
everything specific to that capability:

  - ``contract.py``  Pydantic request/result models
  - ``domain.py``    the real logic - typed in, typed out, imports only
                      ``infra/``, never ``mcp`` or ``flask``. This is what
                      you unit test.
  - ``tool.py``       a few lines: load config, call the domain function,
                      return its result. ``@mcp.tool()`` appears here and
                      nowhere else.

Shared infrastructure (``infra/ssh.py``, ``infra/sap_config.py``) stays one
level up, at ``mcp_server/infra/`` - every capability uses the same SSH
client and config loader rather than each folder inventing its own.

Add a new capability by:
  1. mkdir capabilities/<name>/ with an __init__.py
  2. capabilities/<name>/contract.py
  3. capabilities/<name>/domain.py
  4. capabilities/<name>/tool.py
  5. Add `from mcp_server.capabilities.<name> import tool` to run.py
"""
