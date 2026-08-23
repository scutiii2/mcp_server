import logging
from datetime import datetime
from pathlib import Path

_LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class DailyFileHandler(logging.Handler):
    def __init__(self, logs_dir: str | Path):
        super().__init__()
        self.logs_dir = Path(logs_dir)

    def current_log_path(self) -> Path:
        return self.logs_dir / f"{datetime.now():%m%d%Y}.txt"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            message = self.format(record)
            with self.current_log_path().open("a", encoding="utf-8") as f:
                f.write(message + "\n")
        except Exception:
            self.handleError(record)


def get_logger(name: str, logs_dir: str | Path = "src/logs") -> logging.Logger:
    logger = logging.getLogger(name)
    logs_dir = Path(logs_dir)
    has_handler = any(
        isinstance(h, DailyFileHandler) and h.logs_dir == logs_dir for h in logger.handlers
    )
    if not has_handler:
        handler = DailyFileHandler(logs_dir)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
