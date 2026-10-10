from __future__ import annotations

import pytest

from src.services.ticket_store import AutoLimit, TicketStore

T0 = "2026-10-10T10:00:00+00:00"
T1 = "2026-10-10T11:00:00+00:00"
T2 = "2026-10-10T12:00:00+00:00"


@pytest.fixture
def store(tmp_path):
    return TicketStore(tmp_path / "tickets.db")


def add(store, **over):
    args = dict(
        reporter="alice", type="bug", title="Email fails", description="It does not send", source="user",
        tags=["email"], context={}, fingerprint=None, group_id=None, possible_group_id=None, now=T0,
    )
    args.update(over)
    return store.insert_ticket(**args)


def test_reading_an_empty_store_creates_no_file(tmp_path):
    path = tmp_path / "x" / "tickets.db"
    store = TicketStore(path)
    assert store.get_ticket(1) is None
    assert store.list_tickets() == []
    assert store.list_groups(since=T0) == []
    assert store.stats() == {"open": 0, "urgent": 0, "groups": 0}
    assert not path.exists()


def test_insert_creates_group_and_roundtrips_fields(store):
    ticket_id, created, group_id = add(store, context={"reported": {"agent": "ember"}})

    ticket = store.get_ticket(ticket_id)
    assert created is True and ticket["group_id"] == group_id
    assert ticket["status"] == "open" and ticket["priority"] == "normal"
    assert ticket["tags"] == ["email"] and ticket["context"] == {"reported": {"agent": "ember"}}
    assert ticket["effective_priority"] == "normal" and ticket["group_pinned"] is False
    assert "fingerprint" not in ticket
    assert store.get_group(group_id)["title"] == "Email fails"


def test_joining_a_group_reuses_it(store):
    _, _, group_id = add(store)
    second, created, joined = add(store, reporter="bob", group_id=group_id, now=T1)

    assert created and joined == group_id
    assert store.group_counts(group_id, T1) == (2, 1)
    assert store.get_ticket(second)["reporter"] == "bob"


def test_open_auto_ticket_with_same_fingerprint_is_returned_not_duplicated(store):
    first, created, _ = add(store, source="ai_auto", fingerprint="abc")
    again, created_again, _ = add(store, source="ai_auto", fingerprint="abc", now=T1)

    assert created and not created_again and again == first
    assert store.find_open_auto("alice", "abc") == first
    assert store.find_open_auto("bob", "abc") is None


def test_closed_auto_ticket_allows_a_new_one(store):
    first, _, _ = add(store, source="ai_auto", fingerprint="abc")
    store.update_ticket(first, {"status": "resolved"}, T1)

    second, created, _ = add(store, source="ai_auto", fingerprint="abc", now=T2)

    assert created and second != first
    assert store.find_open_auto("alice", "abc") == second


def test_auto_cap_counts_only_the_reporters_recent_auto_tickets(store):
    add(store, source="ai_auto", fingerprint="a", now=T1)
    add(store, source="ai_auto", fingerprint="b", now=T2)
    add(store, source="user", now=T2)

    with pytest.raises(AutoLimit):
        add(store, source="ai_auto", fingerprint="c", now=T2, auto_cap=2, auto_since=T0)
    add(store, source="ai_auto", fingerprint="d", reporter="bob", now=T2, auto_cap=2, auto_since=T0)
    add(store, source="ai_auto", fingerprint="e", now=T2, auto_cap=2, auto_since=T2)  # older ones fall outside


def test_list_filters_and_ownership(store):
    a, _, _ = add(store, tags=["email", "config"])
    b, _, _ = add(store, reporter="bob", type="feature", title="Dark mode", tags=["ui"], now=T1)

    assert [t["id"] for t in store.list_tickets()] == [b, a]
    assert [t["id"] for t in store.list_tickets(reporter="alice")] == [a]
    assert [t["id"] for t in store.list_tickets(tag="ui")] == [b]
    assert [t["id"] for t in store.list_tickets(type="bug")] == [a]
    assert store.list_tickets(status="closed") == []
    assert [t["id"] for t in store.list_tickets(limit=1)] == [b]


def test_priority_filter_uses_the_higher_of_ticket_and_group(store):
    a, _, group_id = add(store)
    store.update_group(group_id, priority="high", pinned=True, now=T1)

    assert [t["id"] for t in store.list_tickets(priority="high")] == [a]
    assert store.get_ticket(a)["effective_priority"] == "high"
    assert store.list_tickets(priority="normal") == []


def test_possible_group_hint_filter(store):
    _, _, g1 = add(store)
    hinted, _, _ = add(store, reporter="bob", possible_group_id=g1, now=T1)

    assert [t["id"] for t in store.list_tickets(possible_only=True)] == [hinted]


def test_candidates_are_newest_open_per_group_with_tag_overlap(store):
    old, _, g1 = add(store, tags=["email"])
    newer, _, _ = add(store, reporter="bob", group_id=g1, tags=["email"], now=T1)
    other, _, _ = add(store, reporter="cy", title="UI glitch", tags=["ui"], now=T1)
    closed, _, _ = add(store, reporter="di", title="Old", tags=["email"], now=T0)
    store.update_ticket(closed, {"status": "closed"}, T1)
    feature, _, _ = add(store, reporter="ed", type="feature", tags=["email"], now=T1)

    email = store.candidates("bug", ["email"], 5)
    assert [t["id"] for t in email] == [newer]
    assert [t["id"] for t in store.candidates("bug", [], 5)] == [other, newer]
    assert [t["id"] for t in store.candidates("feature", ["email"], 5)] == [feature]
    assert old not in [t["id"] for t in email]


def test_comments_order_and_touch_updated_at(store):
    ticket_id, _, _ = add(store)
    store.add_comment(ticket_id, "alice", "reporter", "more info", T1)
    store.add_comment(ticket_id, "root", "staff", "thanks", T2)

    comments = store.list_comments(ticket_id)
    assert [c["author_role"] for c in comments] == ["reporter", "staff"]
    assert store.get_ticket(ticket_id)["updated_at"] == T2


def test_update_ticket_whitelist_and_closed_at(store):
    ticket_id, _, _ = add(store)

    assert store.update_ticket(ticket_id, {"status": "closed", "assignee": "root", "tags": ["config"]}, T1)
    closed = store.get_ticket(ticket_id)
    assert closed["status"] == "closed" and closed["closed_at"] == T1
    assert closed["assignee"] == "root" and closed["tags"] == ["config"]

    store.update_ticket(ticket_id, {"status": "open", "assignee": None}, T2)
    reopened = store.get_ticket(ticket_id)
    assert reopened["closed_at"] is None and reopened["assignee"] is None

    with pytest.raises(ValueError):
        store.update_ticket(ticket_id, {"reporter": "mallory"}, T2)
    assert store.update_ticket(999, {"status": "open"}, T2) is False


def test_move_ticket_between_groups_and_split_out(store):
    a, _, g1 = add(store)
    b, _, g2 = add(store, reporter="bob", title="Different", now=T1)

    assert store.move_ticket(b, g1, T2) == g1
    assert store.get_ticket(b)["group_id"] == g1
    assert store.list_groups(since=T0)[0]["ticket_count"] == 2

    split = store.move_ticket(b, None, T2)
    assert split not in (g1, g2) and store.get_group(split)["title"] == "Different"
    assert store.move_ticket(b, 999, T2) is None
    assert store.move_ticket(999, g1, T2) is None


def test_group_priority_and_pin(store):
    _, _, group_id = add(store)

    assert store.update_group(group_id, priority="urgent", pinned=True, now=T1)
    group = store.get_group(group_id)
    assert group["priority"] == "urgent" and group["priority_pinned"] is True
    assert store.update_group(group_id, pinned=False, now=T2)
    assert store.get_group(group_id)["priority_pinned"] is False
    assert store.update_group(999, priority="low", now=T2) is False


def test_list_groups_aggregates_and_filters(store):
    _, _, g1 = add(store, tags=["email"])
    add(store, reporter="bob", group_id=g1, tags=["config"], now=T1)
    _, _, g2 = add(store, reporter="cy", title="UI", tags=["ui"], now=T2)

    groups = store.list_groups(since=T1)
    by_id = {g["id"]: g for g in groups}
    assert [g["id"] for g in groups] == [g2, g1]  # newest activity first
    assert by_id[g1]["ticket_count"] == 2 and by_id[g1]["recent_count"] == 1
    assert by_id[g1]["tags"] == ["config", "email"] and by_id[g1]["open_count"] == 2
    assert [g["id"] for g in store.list_groups(since=T1, tag="ui")] == [g2]
    assert [g["id"] for g in store.list_groups(since=T1, status="closed")] == []
    assert [g["id"] for g in store.list_groups(since=T1, priority="normal")] == [g2, g1]


def test_stats(store):
    a, _, g1 = add(store)
    add(store, reporter="bob", title="Other", now=T1)
    store.update_group(g1, priority="urgent", pinned=True, now=T1)
    closed, _, _ = add(store, reporter="cy", title="Done", now=T1)
    store.update_ticket(closed, {"status": "closed"}, T2)

    assert store.stats() == {"open": 2, "urgent": 1, "groups": 2}
