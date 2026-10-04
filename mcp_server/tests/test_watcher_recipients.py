import pytest

from src.services.watcher_recipients import get_recipients, parse_recipients, set_recipients


def test_parse_splits_dedupes_and_validates():
    assert parse_recipients("a@x.com, B@x.com;a@X.com  c@y.org") == ["a@x.com", "B@x.com", "c@y.org"]
    assert parse_recipients("") == []
    with pytest.raises(ValueError):
        parse_recipients("a@x.com, nope")


def test_set_get_and_clear(tmp_path):
    set_recipients(tmp_path, "W", "k1", ["a@x.com"])
    set_recipients(tmp_path, "W", "k2", ["b@x.com"])
    assert get_recipients(tmp_path, "W", "k1") == ["a@x.com"]
    set_recipients(tmp_path, "W", "k1", [])
    assert get_recipients(tmp_path, "W", "k1") == []
    assert get_recipients(tmp_path, "W", "k2") == ["b@x.com"]
    assert get_recipients(tmp_path, "Other", "k2") == []


def test_add_recipient_appends_without_duplicating(tmp_path):
    from src.services.watcher_recipients import add_recipient
    assert add_recipient(tmp_path, "W", "k", "a@x.com") == ["a@x.com"]
    assert add_recipient(tmp_path, "W", "k", "b@x.com") == ["a@x.com", "b@x.com"]
    assert add_recipient(tmp_path, "W", "k", "A@X.com") == ["a@x.com", "b@x.com"]
    for bad in ("", "nope", "a@x.com, b@x.com"):
        with pytest.raises(ValueError):
            add_recipient(tmp_path, "W", "k", bad)


def test_remove_recipient(tmp_path):
    from src.services.watcher_recipients import add_recipient, remove_recipient
    add_recipient(tmp_path, "W", "k", "a@x.com")
    add_recipient(tmp_path, "W", "k", "b@x.com")
    assert remove_recipient(tmp_path, "W", "k", "A@X.com") == (["b@x.com"], True)
    assert remove_recipient(tmp_path, "W", "k", "zzz@x.com") == (["b@x.com"], False)
    assert remove_recipient(tmp_path, "W", "k", "b@x.com") == ([], True)
    with pytest.raises(ValueError):
        remove_recipient(tmp_path, "W", "k", "not-an-email")
