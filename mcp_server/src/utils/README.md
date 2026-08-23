# src/utils/

Small, single-purpose helper modules with no knowledge of any specific
capability - mirrors chat_app/src/utils/'s role in that project.

- `logging_setup.py` - `configure_logging(log_dir)`, called once from
  `run.py`, wires the root logger to `src/logs/server.log` (rotating)
  plus stderr.

If a helper only one capability or one infra client uses, it belongs
next to that code instead - this folder is for the ones nothing else
already owns.
