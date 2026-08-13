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
  5. Add `from mcp_server.capabilities.<name> import tool` to run.py

Nothing is registered yet - this is an empty scaffold.
"""
