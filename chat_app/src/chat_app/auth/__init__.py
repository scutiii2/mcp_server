"""User accounts, invite codes, and login sessions.

``store.py`` is the SQLite-backed persistence layer (mirrors
``mcp_server/infra/otp.py``'s style: stdlib ``sqlite3``, salted hashes,
atomic claim-by-UPDATE). ``service.py`` sits above it and is what the rest
of the app talks to - session state plus the env-configured default user.
"""
