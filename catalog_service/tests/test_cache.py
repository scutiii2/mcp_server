from __future__ import annotations

from src.cache import load_cache, save_cache_atomic


def test_load_cache_returns_none_when_file_missing(tmp_path):
    assert load_cache(tmp_path / "missing.json") is None


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "data" / "catalog_cache.json"
    entries = [{"id": "a.b.c", "type": "function"}]

    save_cache_atomic(path, entries)

    assert load_cache(path) == entries


def test_save_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "catalog_cache.json"

    save_cache_atomic(path, [])

    assert path.exists()


def test_load_cache_returns_none_for_corrupt_file(tmp_path):
    path = tmp_path / "catalog_cache.json"
    path.write_text("not json", encoding="utf-8")

    assert load_cache(path) is None


def test_save_leaves_no_temp_files_behind(tmp_path):
    path = tmp_path / "catalog_cache.json"

    save_cache_atomic(path, [{"id": "a"}])

    assert list(tmp_path.iterdir()) == [path]


def test_load_cache_returns_none_for_invalid_utf8(tmp_path):
    path = tmp_path / "catalog_cache.json"
    path.write_bytes(b"\xff\xfe not valid utf-8")

    assert load_cache(path) is None


def test_load_cache_returns_none_when_json_is_not_a_list(tmp_path):
    # Regression test for Finding 2: valid JSON that isn't a list of
    # entry-dicts (e.g. a plain object) must be treated as corrupt, not
    # assigned straight into the registry (which would later crash
    # get_by_id with an uncaught TypeError - a 500 on a public route).
    path = tmp_path / "catalog_cache.json"
    path.write_text('{"not": "a list"}', encoding="utf-8")

    assert load_cache(path) is None


def test_load_cache_returns_none_when_list_contains_non_dict_element(tmp_path):
    path = tmp_path / "catalog_cache.json"
    path.write_text('[{"id": "a.b.c"}, "not-a-dict"]', encoding="utf-8")

    assert load_cache(path) is None
