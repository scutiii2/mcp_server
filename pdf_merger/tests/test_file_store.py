from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from src.errors import ErrorCode, MergerError
from src.store.file_store import FileStore


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def chunks(data: bytes, size: int = 4) -> AsyncIterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


def make_store(tmp_path: Path, clock: FakeClock, **overrides) -> FileStore:
    options = dict(ttl_seconds=100, max_file_bytes=1000, max_session_bytes=2000, clock=clock)
    options.update(overrides)
    return FileStore(tmp_path / "store", **options)


async def add(store: FileStore, session: str, data: bytes = b"hello", name: str = "a.pdf"):
    pending = await store.write_stream(session, chunks(data))
    return await store.commit(pending, name=name, mime="application/pdf", kind="pdf", pages=1)


async def test_commit_then_get_and_read(tmp_path: Path):
    store = make_store(tmp_path, FakeClock())

    stored = await add(store, "web:1", b"content")

    assert stored.file_id.startswith("f_") and len(stored.file_id) == 34
    assert stored.size == 7 and stored.expires_at == 1100.0
    assert store.get(stored.file_id, "web:1") == stored
    assert store.path(stored).read_bytes() == b"content"


async def test_other_session_gets_not_found_but_privileged_caller_can_read(tmp_path: Path):
    store = make_store(tmp_path, FakeClock())
    stored = await add(store, "web:1")

    with pytest.raises(MergerError) as caught:
        store.get(stored.file_id, "web:2")
    assert caught.value.code == ErrorCode.FILE_NOT_FOUND
    assert store.get(stored.file_id, None) == stored


async def test_expired_file_is_not_found_and_swept(tmp_path: Path):
    clock = FakeClock()
    store = make_store(tmp_path, clock)
    stored = await add(store, "web:1")
    path = store.path(stored)

    clock.now += 101
    with pytest.raises(MergerError):
        store.get(stored.file_id, "web:1")
    assert await store.sweep() == 1
    assert not path.exists()


async def test_too_large_stream_is_rejected_and_cleaned_up(tmp_path: Path):
    store = make_store(tmp_path, FakeClock(), max_file_bytes=10)

    with pytest.raises(MergerError) as caught:
        await store.write_stream("web:1", chunks(b"x" * 11))

    assert caught.value.code == ErrorCode.FILE_TOO_LARGE
    assert list((tmp_path / "store").rglob("*.part")) == []


async def test_session_quota(tmp_path: Path):
    store = make_store(tmp_path, FakeClock(), max_session_bytes=10)
    await add(store, "web:1", b"x" * 6)

    with pytest.raises(MergerError) as caught:
        await add(store, "web:1", b"x" * 6)

    assert caught.value.code == ErrorCode.LIMIT_EXCEEDED
    assert store.session_usage("web:1") == 6
    await add(store, "web:2", b"x" * 6)  # other sessions have their own quota


async def test_list_is_per_session_oldest_first(tmp_path: Path):
    clock = FakeClock()
    store = make_store(tmp_path, clock)
    first = await add(store, "web:1", name="first.pdf")
    clock.now += 1
    second = await add(store, "web:1", name="second.pdf")
    await add(store, "web:2")

    assert store.list("web:1") == [first, second]


async def test_delete(tmp_path: Path):
    store = make_store(tmp_path, FakeClock())
    stored = await add(store, "web:1")

    await store.delete(stored.file_id, "web:1")

    with pytest.raises(MergerError):
        store.get(stored.file_id, None)
    assert not store.path(stored).exists()


async def test_index_survives_restart(tmp_path: Path):
    clock = FakeClock()
    stored = await add(make_store(tmp_path, clock), "mcp:alice")

    reopened = make_store(tmp_path, clock)
    assert await reopened.load_index() == 1
    assert reopened.get(stored.file_id, "mcp:alice") == stored


async def test_session_names_never_become_raw_paths(tmp_path: Path):
    store = make_store(tmp_path, FakeClock())
    stored = await add(store, "mcp:../../evil")

    assert store.path(stored).resolve().is_relative_to((tmp_path / "store").resolve())


async def test_work_dir_round_trip(tmp_path: Path):
    store = make_store(tmp_path, FakeClock())

    work = await store.make_work_dir()
    (work / "x.pdf").write_bytes(b"x")
    await store.remove_work_dir(work)

    assert not work.exists()


async def test_concurrent_quota_check(tmp_path: Path):
    store = make_store(tmp_path, FakeClock(), max_session_bytes=10)

    results = await asyncio.gather(
        add(store, "web:1", b"x" * 6),
        add(store, "web:1", b"x" * 6),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], MergerError)
    assert failures[0].code == ErrorCode.LIMIT_EXCEEDED
    assert store.session_usage("web:1") == 6


async def test_removal_with_permission_error(tmp_path: Path, monkeypatch):
    clock = FakeClock()
    store = make_store(tmp_path, clock)
    stored1 = await add(store, "web:1", name="first.pdf")
    stored2 = await add(store, "web:1", name="second.pdf")

    # Advance clock to expire both files
    clock.now += 101

    # Make one file's unlink fail
    original_unlink = Path.unlink
    call_count = [0]

    def failing_unlink(self, missing_ok=False):
        call_count[0] += 1
        if call_count[0] == 1:  # First unlink call fails
            raise PermissionError("File in use")
        return original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    # Sweep should continue and remove only the second file
    removed = await store.sweep()
    assert removed == 1

    # First file should still be in index (for retry)
    assert store._index[stored1.file_id] == stored1

    # Remove the patch
    monkeypatch.setattr(Path, "unlink", original_unlink)

    # Second sweep should succeed for the first file
    removed = await store.sweep()
    assert removed == 1
    assert stored1.file_id not in store._index
