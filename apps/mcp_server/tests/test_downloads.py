"""The in-memory store of files a tool offers (services/downloads.py)."""

from __future__ import annotations

import re
import threading

import pytest

from src.services import downloads
from src.services.downloads import DownloadRefused, DownloadRegistry, marker, safe_filename


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


def make(clock: Clock, **kwargs) -> DownloadRegistry:
    return DownloadRegistry(clock=clock, **kwargs)


class TestOwner:
    def test_the_owner_gets_the_file(self, clock: Clock) -> None:
        registry = make(clock)
        entry = registry.offer("alice", "web.log", b"hello")

        got = registry.get(entry.id, "alice")

        assert got is not None and got.data == b"hello" and got.filename == "web.log"

    def test_another_account_gets_nothing(self, clock: Clock) -> None:
        registry = make(clock)
        entry = registry.offer("alice", "web.log", b"hello")

        assert registry.get(entry.id, "bob") is None

    def test_no_identity_gets_nothing(self, clock: Clock) -> None:
        registry = make(clock)
        entry = registry.offer("alice", "web.log", b"hello")

        assert registry.get(entry.id, "") is None

    def test_names_that_differ_only_in_case_are_different_accounts(self, clock: Clock) -> None:
        registry = make(clock)
        entry = registry.offer("alice", "web.log", b"hello")

        assert registry.get(entry.id, "Alice") is None

    def test_an_unknown_id_gets_nothing(self, clock: Clock) -> None:
        assert make(clock).get("nope", "alice") is None

    def test_a_file_cannot_be_offered_to_nobody(self, clock: Clock) -> None:
        with pytest.raises(DownloadRefused, match="not identified"):
            make(clock).offer("", "web.log", b"hello")


class TestIds:
    def test_ids_are_random_and_long_enough_to_not_be_guessed(self, clock: Clock) -> None:
        registry = make(clock)

        ids = {registry.offer("alice", "a.log", b"x").id for _ in range(20)}

        assert len(ids) == 20
        assert all(len(i) >= 20 and re.fullmatch(r"[A-Za-z0-9_-]+", i) for i in ids)


class TestExpiry:
    def test_it_is_there_until_the_time_is_up(self, clock: Clock) -> None:
        registry = make(clock, ttl_seconds=600)
        entry = registry.offer("alice", "a.log", b"x")

        clock.now += 599
        assert registry.get(entry.id, "alice") is not None
        clock.now += 1
        assert registry.get(entry.id, "alice") is None

    def test_the_default_is_ten_minutes(self) -> None:
        assert downloads.TTL_SECONDS == 600

    def test_an_expired_entry_frees_its_space(self, clock: Clock) -> None:
        registry = make(clock, ttl_seconds=10)
        registry.offer("alice", "a.log", b"x" * 100)

        clock.now += 11

        assert len(registry) == 0
        assert registry._total == 0


class TestLimits:
    def test_a_file_over_the_limit_is_refused(self, clock: Clock) -> None:
        registry = make(clock, max_file_bytes=10)

        registry.offer("alice", "a.log", b"x" * 10)
        with pytest.raises(DownloadRefused, match="larger than"):
            registry.offer("alice", "a.log", b"x" * 11)

    def test_the_real_limits_are_the_documented_ones(self) -> None:
        assert (downloads.MAX_ENTRIES, downloads.MAX_FILE_BYTES, downloads.MAX_TOTAL_BYTES) == (
            50,
            5 * 1024 * 1024,
            50 * 1024 * 1024,
        )

    def test_the_oldest_goes_first_when_there_are_too_many(self, clock: Clock) -> None:
        registry = make(clock, max_entries=3)
        first = registry.offer("alice", "1.log", b"1")
        second = registry.offer("alice", "2.log", b"2")
        third = registry.offer("alice", "3.log", b"3")

        fourth = registry.offer("alice", "4.log", b"4")

        assert registry.get(first.id, "alice") is None
        assert [registry.get(e.id, "alice") is not None for e in (second, third, fourth)] == [True] * 3
        assert len(registry) == 3

    def test_the_oldest_goes_first_when_the_total_is_too_big(self, clock: Clock) -> None:
        registry = make(clock, max_total_bytes=100)
        first = registry.offer("alice", "1.log", b"x" * 60)
        second = registry.offer("alice", "2.log", b"x" * 30)

        third = registry.offer("alice", "3.log", b"x" * 50)

        assert registry.get(first.id, "alice") is None
        assert registry.get(second.id, "alice") is not None
        assert registry.get(third.id, "alice") is not None
        assert registry._total == 80

    def test_a_file_that_makes_the_total_exactly_the_limit_still_fits(self, clock: Clock) -> None:
        registry = make(clock, max_total_bytes=100)
        first = registry.offer("alice", "1.log", b"x" * 60)

        second = registry.offer("alice", "2.log", b"x" * 40)

        assert registry.get(first.id, "alice") is not None
        assert registry.get(second.id, "alice") is not None
        assert registry._total == 100

    def test_the_total_is_exact_after_drops(self, clock: Clock) -> None:
        registry = make(clock, max_entries=2)
        for size in (10, 20, 30, 40):
            registry.offer("alice", "a.log", b"x" * size)

        assert registry._total == 70 and len(registry) == 2

    def test_many_threads_leave_a_consistent_store(self, clock: Clock) -> None:
        registry = make(clock, max_entries=10)

        def work() -> None:
            for _ in range(50):
                registry.offer("alice", "a.log", b"x" * 7)

        threads = [threading.Thread(target=work) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(registry) == 10 and registry._total == 70


class TestFilenames:
    @pytest.mark.parametrize(
        "given, expected",
        [
            ("web.log", "web.log"),
            ("../../etc/passwd", "passwd"),
            ("C:\\data\\x.log", "x.log"),
            ('a"b]c.log', "a_b_c.log"),
            ("spaces and\nnewlines.log", "spaces_and_newlines.log"),
            ("", "download"),
            ("...", "download"),
            ("\u00e9t\u00e9.log", "t_.log"),
        ],
    )
    def test_a_name_is_made_safe(self, given: str, expected: str) -> None:
        assert safe_filename(given) == expected

    def test_a_long_name_is_cut(self) -> None:
        assert len(safe_filename("a" * 500 + ".log")) == 100

    def test_the_offered_file_keeps_the_safe_name(self, clock: Clock) -> None:
        entry = make(clock).offer("alice", '../x"y.log', b"x")

        assert entry.filename == "x_y.log"


class TestMarker:
    def test_the_marker_has_the_shape_the_chat_page_reads(self, clock: Clock) -> None:
        entry = make(clock).offer("alice", "web-logs.log", b"x" * 31204)

        text = marker(entry, "LOGS")

        # The same pattern as ember_web/src/utils/downloads.ts.
        pattern = r'\[\[DOWNLOAD filename="([^"]*)" bytes="(\d+)" url="([^"]*)"(?: label="([^"]*)")?\]\]'
        match = re.fullmatch(pattern, text)
        assert match is not None
        assert match.groups() == ("web-logs.log", "31204", f"/server/download?path={entry.id}", "LOGS")

    def test_the_link_is_the_route_the_page_accepts(self, clock: Clock) -> None:
        entry = make(clock).offer("alice", "a.log", b"x")

        assert marker(entry).count('url="/server/download?path=') == 1

    @pytest.mark.parametrize("label", ['a"b', "x]]", "", "x" * 31])
    def test_a_label_cannot_break_the_marker(self, clock: Clock, label: str) -> None:
        entry = make(clock).offer("alice", "a.log", b"x")

        with pytest.raises(ValueError):
            marker(entry, label)

    def test_the_module_store_exists(self) -> None:
        assert isinstance(downloads.registry, DownloadRegistry)
