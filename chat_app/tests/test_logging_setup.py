import logging
from datetime import datetime

from src.utils.logging_setup import DailyFileHandler, get_logger


def test_current_log_path_uses_mmddyyyy_format(tmp_path):
    handler = DailyFileHandler(tmp_path)

    expected_name = f"{datetime.now():%m%d%Y}.txt"

    assert handler.current_log_path() == tmp_path / expected_name


def test_get_logger_writes_structured_line_to_dated_file(tmp_path):
    logger = get_logger("test.module.one", logs_dir=str(tmp_path))

    logger.info("hello world")

    expected_file = tmp_path / f"{datetime.now():%m%d%Y}.txt"
    assert expected_file.exists()
    content = expected_file.read_text(encoding="utf-8")
    assert "INFO" in content
    assert "test.module.one" in content
    assert "hello world" in content


def test_get_logger_does_not_duplicate_handlers_on_repeat_calls(tmp_path):
    logger_a = get_logger("test.module.two", logs_dir=str(tmp_path))
    logger_b = get_logger("test.module.two", logs_dir=str(tmp_path))

    assert logger_a is logger_b
    daily_handlers = [h for h in logger_a.handlers if isinstance(h, DailyFileHandler)]
    assert len(daily_handlers) == 1


def test_get_logger_sets_info_level(tmp_path):
    logger = get_logger("test.module.three", logs_dir=str(tmp_path))

    assert logger.level == logging.INFO
