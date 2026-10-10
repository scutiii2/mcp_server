"""Owner-scoped memory notes in SQLite with FTS5 search."""

import pytest

from src.services import memory_store as store


@pytest.fixture
def db(tmp_path):
    return tmp_path / "nested" / "memory.db"


def test_save_then_search_round_trip(db):
    outcome = store.save(db, "alice", "I prefer metric units")
    assert outcome.duplicate is False
    notes = store.search(db, "alice", "metric")
    assert [(n.id, n.text) for n in notes] == [(outcome.id, "I prefer metric units")]
    assert notes[0].created_at.startswith("20")


def test_empty_query_returns_newest_first_and_respects_limit(db):
    for i in range(5):
        store.save(db, "alice", f"note {i}")
    notes = store.search(db, "alice", "", limit=3)
    assert [n.text for n in notes] == ["note 4", "note 3", "note 2"]


def test_search_ranks_matches_and_ignores_non_matches(db):
    store.save(db, "alice", "my server is called app-01")
    store.save(db, "alice", "I like green tea")
    texts = [n.text for n in store.search(db, "alice", "server")]
    assert texts == ["my server is called app-01"]


@pytest.mark.parametrize("query", ['"', "*", "a AND", "NEAR(", "x OR OR y", "(((", "col:val", "---", "???"])
def test_awkward_queries_never_raise(db, query):
    store.save(db, "alice", "plain note")
    store.search(db, "alice", query)


def test_duplicate_is_not_stored_twice(db):
    first = store.save(db, "alice", "Prefers  Dark   mode")
    second = store.save(db, "alice", "prefers dark mode")
    assert second.duplicate is True and second.id == first.id
    assert len(store.search(db, "alice")) == 1


def test_whitespace_is_collapsed_in_the_stored_text(db):
    store.save(db, "alice", "line one\n\n  line two")
    assert store.search(db, "alice")[0].text == "line one line two"


@pytest.mark.parametrize("text", ["", "   \n\t "])
def test_empty_text_is_rejected(db, text):
    with pytest.raises(store.MemoryStoreError, match="empty"):
        store.save(db, "alice", text)


def test_text_over_the_limit_is_rejected(db):
    store.save(db, "alice", "x" * store.MAX_NOTE_CHARS)
    with pytest.raises(store.MemoryStoreError, match="limit is 500"):
        store.save(db, "alice", "x" * (store.MAX_NOTE_CHARS + 1))


def test_note_cap_per_owner(db, monkeypatch):
    monkeypatch.setattr(store, "MAX_NOTES", 3)
    for i in range(3):
        store.save(db, "alice", f"n{i}")
    with pytest.raises(store.MemoryStoreError, match="Forget one first"):
        store.save(db, "alice", "n3")
    store.save(db, "bob", "bob is not blocked by alice's notes")


def test_owners_never_see_each_others_notes(db):
    store.save(db, "alice", "alice secret plan")
    store.save(db, "bob", "bob likes tea")
    assert [n.text for n in store.search(db, "bob", "plan")] == []
    assert [n.text for n in store.search(db, "alice")] == ["alice secret plan"]


def test_forget_removes_only_the_owners_note_from_both_tables(db):
    mine = store.save(db, "alice", "forget me please")
    other = store.save(db, "bob", "bob keeps this")
    assert store.forget(db, "alice", other.id) is False
    assert store.forget(db, "alice", mine.id) is True
    assert store.search(db, "alice", "forget") == []
    assert store.search(db, "alice") == []
    assert [n.text for n in store.search(db, "bob", "keeps")] == ["bob keeps this"]
    assert store.forget(db, "alice", mine.id) is False


def test_note_ids_are_not_reused_after_a_delete(db):
    store.save(db, "alice", "first note")
    second = store.save(db, "alice", "second note")
    assert store.forget(db, "alice", second.id) is True
    third = store.save(db, "alice", "third note")
    assert third.id == second.id + 1 == 3


def test_reading_a_missing_database_creates_nothing(db):
    assert store.search(db, "alice") == []
    assert store.forget(db, "alice", 1) is False
    assert not db.exists()


@pytest.mark.parametrize("owner", ["", "   ", None])
def test_every_operation_refuses_without_an_owner(db, owner):
    with pytest.raises(store.MemoryStoreError, match="signed-in user"):
        store.save(db, owner, "note")
    with pytest.raises(store.MemoryStoreError, match="signed-in user"):
        store.search(db, owner)
    with pytest.raises(store.MemoryStoreError, match="signed-in user"):
        store.forget(db, owner, 1)
    assert not db.exists()
