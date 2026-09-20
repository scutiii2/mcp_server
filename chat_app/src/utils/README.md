# src/utils/

Small, single-purpose helper modules used across the app.

- `config_loader.py` — loads `../../configs/*.json` feature-toggle files
  and `../../secrets/*.env` credential files. Each `.env` is loaded into
  its own isolated dict via `dotenv_values()` (never merged into
  `os.environ`), so secret topics stay independent.
- `logging_setup.py` — daily-rotating file logger factory; every
  service calls `get_logger(__name__)` to get a logger that writes to
  `logs/{MM}{DD}{YYYY}.txt`.
- `tokens.py` — OTP/random token generation and hashing (added in a
  later phase).
- `validators.py` — input validation helpers (added in a later phase).
