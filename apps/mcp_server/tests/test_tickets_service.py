from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from src.services.ticket_config import load_ticket_config
from src.services.ticket_store import TicketStore
from src.services.tickets import TicketError, TicketNotFound, TicketService


class FakeLaya:
    def __init__(self, verdicts=None, tag=None, fail=False):
        self.verdicts, self.tag, self.fail = verdicts or {}, tag, fail
        self.same_calls, self.tag_calls = [], 0

    async def same_issue(self, new, existing):
        self.same_calls.append(existing["group_id"])
        if self.fail:
            raise RuntimeError("laya down")
        return self.verdicts.get(existing["group_id"], "no")

    async def pick_tag(self, ticket, tags):
        self.tag_calls += 1
        if self.fail:
            raise RuntimeError("laya down")
        return self.tag


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def config(tmp_path):
    return load_ticket_config(tmp_path / "missing.json")


@pytest.fixture
def make(tmp_path, config, clock):
    def build(laya=None):
        return TicketService(TicketStore(tmp_path / "t.db"), config, laya, clock=clock)

    return build


def create(service, **over):
    args = dict(reporter="alice", type="bug", title="Email fails", description="It does not send")
    args.update(over)
    args.setdefault("owner", f"uid-{args['reporter'].strip()}" if args["reporter"].strip() else "")
    return asyncio.run(service.create(**args))


def test_basic_create(make):
    service = make()
    outcome = create(service, tags=["email", "bogus"], context={"chat_id": "c1", "evil": "x"},
                     verified_context={"page": "/chat"})

    ticket = outcome.ticket
    assert ticket["status"] == "open" and ticket["source"] == "user"
    assert ticket["tags"] == ["email", "bogus"]
    assert ticket["context"] == {"reported": {"chat_id": "c1"}, "verified": {"page": "/chat"}}
    assert outcome.duplicate is False and outcome.group_size == 1


@pytest.mark.parametrize(
    "over,message",
    [
        ({"owner": " "}, "reporter"),
        ({"type": "complaint"}, "type"),
        ({"title": " "}, "title"),
        ({"title": "x" * 121}, "title"),
        ({"description": ""}, "description"),
        ({"description": "x" * 4001}, "description"),
        ({"source": "robot"}, "source"),
    ],
)
def test_validation_messages(make, over, message):
    with pytest.raises(TicketError, match=message):
        create(make(), **over)


def test_ai_sources_are_redacted_but_user_text_is_not(make):
    service = make()
    secret = "password=hunter22 and mail bob@example.com"

    auto = create(service, source="ai_auto", description=secret,
                  context={"error_text": "Authorization: Bearer abcdefgh12345678 failed"})
    typed = create(service, reporter="bob", description=secret)

    assert "hunter22" not in auto.ticket["description"] and "bob@example.com" not in auto.ticket["description"]
    assert "abcdefgh12345678" not in auto.ticket["context"]["reported"]["error_text"]
    assert "hunter22" in typed.ticket["description"]


def test_context_values_are_capped(make):
    outcome = create(make(), context={"error_text": "e" * 5000, "agent": "a" * 500})
    reported = outcome.ticket["context"]["reported"]
    assert len(reported["error_text"]) == 2000 and len(reported["agent"]) == 100


def test_auto_reports_dedupe_per_reporter_and_fingerprint(make):
    service = make()
    ctx = {"tool_name": "tool_email_sendEmail", "error_text": "Missing key smtp_host in /etc/a.json line 4"}
    first = create(service, source="ai_auto", context=ctx)
    again = create(service, source="ai_auto", context={**ctx, "error_text": "Missing key smtp_host in /srv/b.json line 9"})
    other_user = create(service, source="ai_auto", reporter="bob", context=ctx)

    assert again.duplicate and again.ticket["id"] == first.ticket["id"]
    assert not other_user.duplicate and other_user.ticket["id"] != first.ticket["id"]


def test_auto_reports_hit_an_hourly_cap_that_resets(make, clock):
    service = make()
    for index in range(5):
        create(service, source="ai_auto", context={"tool_name": "t", "error_text": f"error kind{chr(97 + index)}"})

    with pytest.raises(TicketError, match="automatic"):
        create(service, source="ai_auto", context={"tool_name": "t", "error_text": "error kindz"})
    create(service, source="user")  # manual tickets are never capped

    clock.advance(minutes=61)
    create(service, source="ai_auto", context={"tool_name": "t", "error_text": "error kindz"})


def test_without_laya_every_ticket_gets_its_own_group(make):
    service = make()
    a = create(service)
    b = create(service, reporter="bob")

    assert a.ticket["group_id"] != b.ticket["group_id"]


def test_confident_laya_match_joins_the_group_and_keeps_both_tickets(make):
    laya = FakeLaya()
    service = make(laya)
    first = create(service, tags=["email"])
    laya.verdicts = {first.ticket["group_id"]: "yes"}

    second = create(service, reporter="bob", tags=["email"])

    assert second.ticket["group_id"] == first.ticket["group_id"]
    assert second.group_size == 2 and second.ticket["id"] != first.ticket["id"]
    assert second.ticket["possible_group_id"] is None


def test_uncertain_laya_match_keeps_own_group_with_a_hint(make):
    laya = FakeLaya()
    service = make(laya)
    first = create(service, tags=["email"])
    laya.verdicts = {first.ticket["group_id"]: "uncertain"}

    second = create(service, reporter="bob", tags=["email"])

    assert second.ticket["group_id"] != first.ticket["group_id"]
    assert second.ticket["possible_group_id"] == first.ticket["group_id"]


def test_no_match_and_unreachable_laya_never_block_creation(make):
    service = make(FakeLaya(fail=True))
    first = create(service, tags=["email"])
    second = create(service, reporter="bob", tags=["email"])

    assert second.ticket["group_id"] != first.ticket["group_id"]
    assert second.ticket["possible_group_id"] is None


def test_laya_is_asked_only_about_candidates_and_stops_at_first_yes(make, config):
    laya = FakeLaya()
    service = make(laya)
    groups = [create(service, reporter=f"u{i}", title=f"Different {i}", tags=["email"]).ticket["group_id"] for i in range(7)]
    laya.same_calls.clear()
    laya.verdicts = {groups[5]: "yes"}  # candidates come newest first: groups[6], groups[5], ...

    result = create(service, reporter="zed", tags=["email"])

    assert laya.same_calls == [groups[6], groups[5]]
    assert result.group_size == 2 and result.ticket["group_id"] == groups[5]


def test_laya_picks_a_tag_only_when_none_were_given(make):
    laya = FakeLaya(tag="config")
    service = make(laya)

    assert create(service).ticket["tags"] == ["config"]
    assert create(service, reporter="bob", tags=["ui"]).ticket["tags"] == ["ui"]
    assert laya.tag_calls == 1
    assert create(make(FakeLaya(tag=None)), reporter="cy").ticket["tags"] == []


def test_priority_elevates_as_tickets_join_a_group(make):
    laya = FakeLaya()
    service = make(laya)
    first = create(service, tags=["email"])
    laya.verdicts = {first.ticket["group_id"]: "yes"}
    sizes = [create(service, reporter=f"u{i}", tags=["email"]) for i in range(2)]

    assert sizes[-1].group_size == 3
    assert sizes[-1].ticket["effective_priority"] == "high"  # 3 tickets in the group


def test_pinned_group_priority_is_not_elevated(make):
    laya = FakeLaya()
    service = make(laya)
    first = create(service, tags=["email"])
    service._store.update_group(first.ticket["group_id"], priority="low", pinned=True, now="2026-10-10T10:00:00+00:00")
    laya.verdicts = {first.ticket["group_id"]: "yes"}

    for index in range(3):
        last = create(service, reporter=f"u{index}", tags=["email"])

    assert last.ticket["effective_priority"] == "normal"  # ticket's own priority; group stays pinned at low


def run(coro):
    return asyncio.run(coro)


def test_reporter_sees_only_own_tickets_and_gets_404_for_others(make):
    service = make()
    mine = create(service).ticket["id"]
    theirs = create(service, reporter="bob").ticket["id"]

    assert [t["id"] for t in run(service.list_tickets(owner="uid-alice"))] == [mine]
    assert run(service.get_ticket(mine, owner="uid-alice"))["id"] == mine
    with pytest.raises(TicketNotFound):
        run(service.get_ticket(theirs, owner="uid-alice"))
    with pytest.raises(TicketNotFound):
        run(service.get_ticket(999))
    assert run(service.get_ticket(theirs))["reporter"] == "bob"  # staff scope


def test_comments_roles_and_ownership(make):
    service = make()
    ticket_id = create(service).ticket["id"]

    run(service.add_comment(ticket_id, author="alice", role="reporter", body="the log says X", owner="uid-alice"))
    ticket = run(service.add_comment(ticket_id, author="root", role="staff", body="thanks"))

    assert [c["author_role"] for c in ticket["comments"]] == ["reporter", "staff"]
    with pytest.raises(TicketNotFound):
        run(service.add_comment(ticket_id, author="bob", role="reporter", body="hi", owner="uid-bob"))
    with pytest.raises(TicketError, match="role"):
        run(service.add_comment(ticket_id, author="alice", role="admin", body="hi"))
    with pytest.raises(TicketError, match="comment"):
        run(service.add_comment(ticket_id, author="alice", role="reporter", body="x" * 2001))


def test_close_own(make):
    service = make()
    ticket_id = create(service).ticket["id"]

    assert run(service.close_own(ticket_id, "uid-alice"))["status"] == "closed"
    with pytest.raises(TicketNotFound):
        run(service.close_own(ticket_id, "uid-bob"))


def test_staff_update_validates_values_and_clears_assignee(make):
    service = make()
    ticket_id = create(service).ticket["id"]

    updated = run(service.update_ticket(ticket_id, status="in_progress", priority="high", assignee="root", tags=["config", "x"]))
    assert (updated["status"], updated["priority"], updated["assignee"], updated["tags"]) == ("in_progress", "high", "root", ["config", "x"])
    assert run(service.update_ticket(ticket_id, assignee=""))["assignee"] is None
    with pytest.raises(TicketError, match="status"):
        run(service.update_ticket(ticket_id, status="done"))
    with pytest.raises(TicketError, match="priority"):
        run(service.update_ticket(ticket_id, priority="critical"))
    with pytest.raises(TicketNotFound):
        run(service.update_ticket(999, status="open"))


def test_move_ticket_and_split(make):
    service = make()
    a = create(service)
    b = create(service, reporter="bob", title="Other")

    moved = run(service.move_ticket(b.ticket["id"], a.ticket["group_id"]))
    assert moved["group_id"] == a.ticket["group_id"]
    split = run(service.move_ticket(b.ticket["id"], None))
    assert split["group_id"] not in (a.ticket["group_id"], b.ticket["group_id"])
    with pytest.raises(TicketNotFound):
        run(service.move_ticket(b.ticket["id"], 999))


def test_moving_tickets_into_a_group_elevates_it(make):
    service = make()
    tickets = [create(service, reporter=f"u{i}", title=f"T{i}") for i in range(3)]
    target = tickets[0].ticket["group_id"]

    run(service.move_ticket(tickets[1].ticket["id"], target))
    last = run(service.move_ticket(tickets[2].ticket["id"], target))

    assert last["effective_priority"] == "high"


def test_group_priority_pin_and_unpin(make):
    service = make()
    first = create(service)
    group_id = first.ticket["group_id"]

    pinned = run(service.set_group_priority(group_id, priority="urgent"))
    assert pinned["priority"] == "urgent" and pinned["priority_pinned"] is True
    with pytest.raises(TicketError, match="priority"):
        run(service.set_group_priority(group_id, priority="critical"))
    with pytest.raises(TicketNotFound):
        run(service.set_group_priority(999, priority="low"))

    unpinned = run(service.set_group_priority(group_id, pinned=False))
    assert unpinned["priority_pinned"] is False and unpinned["priority"] == "urgent"  # never lowered


def test_list_groups_and_stats(make):
    service = make()
    create(service, tags=["email"])
    create(service, reporter="bob", title="UI", tags=["ui"])

    groups = run(service.list_groups(tag="ui"))
    assert len(groups) == 1 and groups[0]["ticket_count"] == 1
    assert run(service.stats()) == {"open": 2, "urgent": 0, "groups": 2}
    with pytest.raises(TicketError, match="status"):
        run(service.list_tickets(status="done"))


@pytest.mark.parametrize("priority,pinned", [("low", True), ("urgent", False)])
def test_elevation_preserves_concurrent_pin_or_higher_priority(make, monkeypatch, priority, pinned):
    laya = FakeLaya()
    service = make(laya)
    first = create(service, tags=["email"])
    group_id = first.ticket["group_id"]
    laya.verdicts = {group_id: "yes"}

    async def interleave():
        counts_read, staff_finished = asyncio.Event(), asyncio.Event()
        original_db = service._db
        paused = False

        async def pause_after_counts(function, *args, **kwargs):
            nonlocal paused
            result = await original_db(function, *args, **kwargs)
            if function == service._store.group_counts and not paused:
                paused = True
                counts_read.set()
                await staff_finished.wait()
            return result

        monkeypatch.setattr(service, "_db", pause_after_counts)
        filing = asyncio.create_task(service.create(
            owner="uid-bob", reporter="bob", type="bug", title="Email fails", description="Still broken", tags=["email"],
        ))
        await asyncio.wait_for(counts_read.wait(), timeout=5)
        await original_db(service._store.update_group, group_id, priority=priority,
                          pinned=pinned, now=service._now().isoformat())
        staff_finished.set()
        await filing
        group = await original_db(service._store.get_group, group_id)
        assert group["priority"] == priority
        assert group["priority_pinned"] is pinned

    run(interleave())


def test_ai_reports_still_use_configured_tags(make):
    service = make()
    outcome = create(service, source="ai_user_request", tags=["email", "custom"])
    assert outcome.ticket["tags"] == ["email"]


def test_tickets_follow_the_owner_uid_not_the_display_name(make):
    service = make()
    mine = create(service, owner="uid-1", reporter="alice").ticket["id"]
    renamed = create(service, owner="uid-1", reporter="alice2").ticket["id"]  # same account after a rename
    stranger = create(service, owner="uid-2", reporter="alice").ticket["id"]  # a new account that reuses the old name

    own = [t["id"] for t in run(service.list_tickets(owner="uid-1"))]
    assert sorted(own) == sorted([mine, renamed])
    assert run(service.get_ticket(mine, owner="uid-1"))["reporter"] == "alice"  # display name as filed
    with pytest.raises(TicketNotFound):
        run(service.get_ticket(mine, owner="uid-2"))
    with pytest.raises(TicketNotFound):
        run(service.get_ticket(stranger, owner="uid-1"))
    assert [t["id"] for t in run(service.list_tickets(owner="uid-2"))] == [stranger]


def test_the_display_name_falls_back_to_the_owner(make):
    ticket = create(make(), owner="uid-9", reporter="").ticket

    assert ticket["reporter"] == "uid-9"


def test_auto_reports_dedupe_and_cap_per_owner_not_per_name(make):
    service = make()
    ctx = {"tool_name": "tool_x", "error_text": "boom"}
    first = create(service, source="ai_auto", owner="uid-1", reporter="alice", context=ctx)
    again = create(service, source="ai_auto", owner="uid-1", reporter="alice2", context=ctx)
    other = create(service, source="ai_auto", owner="uid-2", reporter="alice", context=ctx)

    assert again.duplicate and again.ticket["id"] == first.ticket["id"]
    assert not other.duplicate


def test_tag_options_include_only_the_owners_custom_tags(make):
    service = make()
    create(service, owner="uid-1", reporter="alice", tags=["my-tag"])
    create(service, owner="uid-2", reporter="bob", tags=["bobs-tag"])

    values = [o["value"] for o in run(service.tag_options("uid-1"))]

    assert "my-tag" in values and "bobs-tag" not in values
