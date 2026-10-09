from __future__ import annotations

from pathlib import Path

import pytest

from src.errors import DownloaderError, ErrorCode
from src.store.file_store import FileStore

MB = 1024 * 1024


def make_store(tmp_path: Path, clock, *, max_file=10 * MB, max_session=20 * MB, ttl=3600) -> FileStore:
    return FileStore(tmp_path / "store", ttl_seconds=ttl, max_file_bytes=max_file, max_session_bytes=max_session, clock=clock)


async def make_source(store: FileStore, size: int = 100, name: str = "v.mp4") -> Path:
    work = await store.make_work_dir()
    source = work / name
    source.write_bytes(b"x" * size)
    return source


async def test_commit_then_get_and_list(tmp_path):
    now = [1000.0]
    store = make_store(tmp_path, lambda: now[0])
    stored = await store.commit_file("web:a", await make_source(store), name="Cat.mp4", mime="video/mp4", kind="video", duration=12.5)

    assert stored.size == 100 and stored.expires_at == 4600
    assert store.path(stored).read_bytes() == b"x" * 100
    assert store.get(stored.file_id, "web:a") == stored
    assert [f.file_id for f in store.list("web:a")] == [stored.file_id]
    assert store.list("web:b") == []


async def test_other_session_cannot_get_but_privileged_can(tmp_path):
    store = make_store(tmp_path, lambda: 1000.0)
    stored = await store.commit_file("web:a", await make_source(store), name="a.mp4", mime="video/mp4", kind="video", duration=None)
    with pytest.raises(DownloaderError) as error:
        store.get(stored.file_id, "web:b")
    assert error.value.code == ErrorCode.FILE_NOT_FOUND
    assert store.get(stored.file_id, None).file_id == stored.file_id


async def test_expired_file_is_hidden_and_swept(tmp_path):
    now = [1000.0]
    store = make_store(tmp_path, lambda: now[0], ttl=60)
    stored = await store.commit_file("web:a", await make_source(store), name="a.mp4", mime="video/mp4", kind="video", duration=None)
    now[0] = 2000.0
    with pytest.raises(DownloaderError):
        store.get(stored.file_id, "web:a")
    assert store.list("web:a") == []
    assert await store.sweep() == 1
    assert not store.path(stored).exists()


async def test_session_quota_enforced_and_source_removed(tmp_path):
    store = make_store(tmp_path, lambda: 1000.0, max_session=150)
    await store.commit_file("web:a", await make_source(store, 100), name="a.mp4", mime="video/mp4", kind="video", duration=None)
    source = await make_source(store, 100, "b.mp4")
    with pytest.raises(DownloaderError) as error:
        await store.commit_file("web:a", source, name="b.mp4", mime="video/mp4", kind="video", duration=None)
    assert error.value.code == ErrorCode.LIMIT_EXCEEDED
    assert not source.exists()


async def test_file_cap_enforced(tmp_path):
    store = make_store(tmp_path, lambda: 1000.0, max_file=50)
    source = await make_source(store, 100)
    with pytest.raises(DownloaderError) as error:
        await store.commit_file("web:a", source, name="a.mp4", mime="video/mp4", kind="video", duration=None)
    assert error.value.code == ErrorCode.TOO_LARGE
    assert not source.exists()


async def test_delete_removes_file_and_sidecar(tmp_path):
    store = make_store(tmp_path, lambda: 1000.0)
    stored = await store.commit_file("web:a", await make_source(store), name="a.mp4", mime="video/mp4", kind="video", duration=None)
    await store.delete(stored.file_id, "web:a")
    assert not store.path(stored).exists()
    with pytest.raises(DownloaderError):
        store.get(stored.file_id, "web:a")


async def test_index_rebuilt_after_restart_and_stale_files_cleaned(tmp_path):
    clock = lambda: 1000.0
    store = make_store(tmp_path, clock)
    stored = await store.commit_file("web:a", await make_source(store), name="a.mp4", mime="video/mp4", kind="video", duration=3.0)
    orphan = store.path(stored).parent / ("f_" + "0" * 32)
    orphan.write_bytes(b"orphan")  # data file without a sidecar
    leftover = await store.make_work_dir()
    (leftover / "half.part").write_bytes(b"half")

    fresh = make_store(tmp_path, clock)
    assert await fresh.load_index() == 1
    assert fresh.get(stored.file_id, "web:a").duration == 3.0
    assert not orphan.exists()
    assert not leftover.exists()


async def test_sidecar_without_data_file_is_dropped_on_load(tmp_path):
    clock = lambda: 1000.0
    store = make_store(tmp_path, clock)
    kept = await store.commit_file("web:a", await make_source(store), name="a.mp4", mime="video/mp4", kind="video", duration=None)
    lost = await store.commit_file("web:a", await make_source(store), name="b.mp4", mime="video/mp4", kind="video", duration=None)
    store.path(lost).unlink()  # data file gone, sidecar left behind
    sidecar = store.path(lost).with_name(lost.file_id + ".json")

    fresh = make_store(tmp_path, clock)
    assert await fresh.load_index() == 1
    assert [f.file_id for f in fresh.list("web:a")] == [kept.file_id]
    assert not sidecar.exists()


async def test_session_names_never_become_paths(tmp_path):
    store = make_store(tmp_path, lambda: 1000.0)
    stored = await store.commit_file("mcp:../../evil", await make_source(store), name="a.mp4", mime="video/mp4", kind="video", duration=None)
    assert (tmp_path / "store") in store.path(stored).parents
