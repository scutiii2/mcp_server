"""Automatic database backups, and the config checks that ask for them."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import stat
import threading
import time
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts.backup_db import main as backup_cli
from src.config import BackupSettings, Settings
from src.services.backup_service import STAMP_FORMAT, BackupError, BackupScheduler, DatabaseBackup
from src.services.config_validation import collect_issues
from tests.conftest import make_settings

T0 = datetime(2026, 10, 3, 12, 0, 0)


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def make_db(path: Path, rows: int = 3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, text TEXT)")
        conn.executemany("INSERT INTO notes (text) VALUES (?)", [(f"row {i}",) for i in range(rows)])
        conn.commit()
    return path


def rows_of(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as conn:
        return [r[0] for r in conn.execute("SELECT text FROM notes ORDER BY id")]


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return make_db(tmp_path / "data" / "ember_api.db")


@pytest.fixture
def clock() -> Clock:
    return Clock()


def backup_of(source: Path, clock: Clock, keep: int = 14) -> DatabaseBackup:
    return DatabaseBackup(source, source.parent / "backups", keep, clock)


class TestDatabaseBackup:
    def test_the_copy_holds_the_same_rows_and_is_named_by_time(self, source: Path, clock: Clock) -> None:
        path = asyncio.run(backup_of(source, clock).run())

        assert path == source.parent / "backups" / "ember_api-20261003-120000.db"
        assert rows_of(path) == ["row 0", "row 1", "row 2"]

    def test_the_source_is_not_changed(self, source: Path, clock: Clock) -> None:
        before = hashlib.sha256(source.read_bytes()).hexdigest()

        asyncio.run(backup_of(source, clock).run())

        assert hashlib.sha256(source.read_bytes()).hexdigest() == before

    def test_the_backup_folder_is_created(self, source: Path, clock: Clock) -> None:
        assert not (source.parent / "backups").exists()

        asyncio.run(backup_of(source, clock).run())

        assert (source.parent / "backups").is_dir()

    def test_a_read_only_database_can_be_backed_up(self, source: Path, clock: Clock) -> None:
        # The source is opened read-only, so even a file nothing may write to is copied.
        os.chmod(source, stat.S_IREAD)
        try:
            path = asyncio.run(backup_of(source, clock).run())
        finally:
            os.chmod(source, stat.S_IWRITE | stat.S_IREAD)

        assert rows_of(path) == ["row 0", "row 1", "row 2"]

    def test_the_copy_is_a_database_of_its_own(self, source: Path, clock: Clock) -> None:
        path = asyncio.run(backup_of(source, clock).run())
        with closing(sqlite3.connect(source)) as conn:
            conn.execute("INSERT INTO notes (text) VALUES ('after')")
            conn.commit()

        assert "after" not in rows_of(path)

    def test_no_partial_file_is_left_behind(self, source: Path, clock: Clock) -> None:
        asyncio.run(backup_of(source, clock).run())

        assert [p.name for p in (source.parent / "backups").iterdir()] == ["ember_api-20261003-120000.db"]

    def test_only_the_newest_are_kept(self, source: Path, clock: Clock) -> None:
        backup = backup_of(source, clock, keep=3)
        for _ in range(6):
            asyncio.run(backup.run())
            clock.advance(hours=1)

        names = [p.name for p in backup.existing()]

        assert names == [
            "ember_api-20261003-150000.db",
            "ember_api-20261003-160000.db",
            "ember_api-20261003-170000.db",
        ]

    def test_keep_one_keeps_exactly_one(self, source: Path, clock: Clock) -> None:
        backup = backup_of(source, clock, keep=1)
        for _ in range(3):
            asyncio.run(backup.run())
            clock.advance(hours=1)

        assert [p.name for p in backup.existing()] == ["ember_api-20261003-140000.db"]

    def test_other_files_in_the_folder_are_never_removed(self, source: Path, clock: Clock) -> None:
        folder = source.parent / "backups"
        folder.mkdir()
        (folder / "notes.txt").write_text("mine")
        (folder / "a_other-20200101-000000.db").write_text("another database")
        backup = backup_of(source, clock, keep=1)
        for _ in range(3):
            asyncio.run(backup.run())
            clock.advance(hours=1)

        assert (folder / "notes.txt").read_text() == "mine"
        assert (folder / "a_other-20200101-000000.db").exists()

    def test_two_backups_in_one_second_make_one_file(self, source: Path, clock: Clock) -> None:
        backup = backup_of(source, clock)

        first = asyncio.run(backup.run())
        second = asyncio.run(backup.run())

        assert first == second and len(backup.existing()) == 1

    def test_a_missing_database_is_an_error_and_makes_no_folder(self, tmp_path: Path, clock: Clock) -> None:
        backup = DatabaseBackup(tmp_path / "nope.db", tmp_path / "backups", 3, clock)

        with pytest.raises(BackupError, match="database not found"):
            asyncio.run(backup.run())

        assert not (tmp_path / "backups").exists()

    def test_a_file_that_is_not_a_database_is_an_error_and_leaves_nothing(self, tmp_path: Path, clock: Clock) -> None:
        bad = tmp_path / "data" / "ember_api.db"
        bad.parent.mkdir()
        bad.write_bytes(b"this is not an sqlite file " * 100)
        backup = backup_of(bad, clock)

        with pytest.raises(BackupError):
            asyncio.run(backup.run())

        assert list((bad.parent / "backups").iterdir()) == []

    def test_a_failed_backup_keeps_the_older_ones(self, source: Path, clock: Clock) -> None:
        backup = backup_of(source, clock, keep=2)
        asyncio.run(backup.run())
        clock.advance(hours=1)
        source.write_bytes(b"corrupted " * 200)

        with pytest.raises(BackupError):
            asyncio.run(backup.run())

        assert [p.name for p in backup.existing()] == ["ember_api-20261003-120000.db"]

    def test_a_copy_that_fails_its_check_is_removed(self, source: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(DatabaseBackup, "_integrity", staticmethod(lambda database: "*** in database main ***"))
        backup = backup_of(source, clock)

        with pytest.raises(BackupError, match="integrity check"):
            asyncio.run(backup.run())

        assert list((source.parent / "backups").iterdir()) == []

    def test_a_copy_that_passes_its_check_is_kept(self, source: Path, clock: Clock) -> None:
        # The real check, on a real copy.
        assert asyncio.run(backup_of(source, clock).run()).exists()

    def test_the_check_reads_sqlites_answer(self, source: Path) -> None:
        with closing(sqlite3.connect(source)) as conn:
            assert DatabaseBackup._integrity(conn) == "ok"

    def test_a_backup_made_while_the_database_is_being_written_is_whole(self, source: Path, clock: Clock) -> None:
        stop = threading.Event()
        written = []

        def writer() -> None:
            conn = sqlite3.connect(source, timeout=10)
            i = 0
            while not stop.is_set():
                conn.execute("INSERT INTO notes (text) VALUES (?)", (f"w{i}",))
                conn.commit()
                written.append(i)
                i += 1
            conn.close()

        thread = threading.Thread(target=writer)
        thread.start()
        try:
            time.sleep(0.2)
            path = asyncio.run(backup_of(source, clock).run())
        finally:
            stop.set()
            thread.join()

        with closing(sqlite3.connect(path)) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert conn.execute("SELECT count(*) FROM notes").fetchone()[0] >= 3

    def test_keep_must_be_at_least_one(self, source: Path) -> None:
        with pytest.raises(ValueError):
            DatabaseBackup(source, source.parent / "b", 0)

    def test_run_does_not_block_the_event_loop(self, source: Path, clock: Clock) -> None:
        async def main() -> int:
            ticks = 0

            async def ticker() -> None:
                nonlocal ticks
                while True:
                    await asyncio.sleep(0)
                    ticks += 1

            task = asyncio.create_task(ticker())
            await backup_of(source, clock).run()
            task.cancel()
            return ticks

        assert asyncio.run(main()) > 0


class TestDue:
    def test_no_backup_means_due_now(self, source: Path, clock: Clock) -> None:
        assert backup_of(source, clock).seconds_until_due(timedelta(hours=24)) == 0

    def test_a_fresh_backup_is_not_due_until_the_interval_has_passed(self, source: Path, clock: Clock) -> None:
        backup = backup_of(source, clock)
        asyncio.run(backup.run())
        clock.advance(hours=5)

        assert backup.seconds_until_due(timedelta(hours=24)) == 19 * 3600

    def test_it_is_due_exactly_at_the_interval_and_after(self, source: Path, clock: Clock) -> None:
        backup = backup_of(source, clock)
        asyncio.run(backup.run())
        clock.advance(hours=24)
        assert backup.seconds_until_due(timedelta(hours=24)) == 0
        clock.advance(hours=3)
        assert backup.seconds_until_due(timedelta(hours=24)) == 0

    def test_the_newest_backup_decides(self, source: Path, clock: Clock) -> None:
        backup = backup_of(source, clock)
        asyncio.run(backup.run())
        clock.advance(hours=30)
        asyncio.run(backup.run())
        clock.advance(hours=1)

        assert backup.seconds_until_due(timedelta(hours=24)) == 23 * 3600

    def test_a_file_with_an_unreadable_name_counts_as_due(self, source: Path, clock: Clock) -> None:
        folder = source.parent / "backups"
        folder.mkdir()
        (folder / "ember_api-garbage.db").write_text("x")

        assert backup_of(source, clock).seconds_until_due(timedelta(hours=24)) == 0

    def test_the_stamp_format_round_trips(self) -> None:
        assert datetime.strptime(T0.strftime(STAMP_FORMAT), STAMP_FORMAT) == T0


class TestScheduler:
    def run_loop(self, backup: DatabaseBackup, every: timedelta, rounds: int, on_error=None) -> list[float]:
        """Runs the scheduler for `rounds` sleeps, with sleeping replaced by a log."""
        sleeps: list[float] = []

        async def main() -> None:
            done = asyncio.Event()

            async def fake_sleep(seconds: float) -> None:
                sleeps.append(seconds)
                if len(sleeps) >= rounds:
                    done.set()
                    await asyncio.sleep(3600)

            scheduler = BackupScheduler(backup, every, on_error=on_error, sleep=fake_sleep)
            scheduler.start()
            await asyncio.wait_for(done.wait(), 10)
            await scheduler.stop()

        asyncio.run(main())
        return sleeps

    def test_the_first_backup_is_made_at_once_when_none_exists(self, source: Path, clock: Clock) -> None:
        backup = backup_of(source, clock)

        sleeps = self.run_loop(backup, timedelta(hours=24), rounds=2)

        assert sleeps[0] == 0
        assert len(backup.existing()) == 1
        assert sleeps[1] == 24 * 3600  # then it waits a whole interval

    def test_a_restart_waits_out_the_rest_of_the_interval(self, source: Path, clock: Clock) -> None:
        backup = backup_of(source, clock)
        asyncio.run(backup.run())
        clock.advance(hours=10)

        sleeps = self.run_loop(backup, timedelta(hours=24), rounds=1)

        assert sleeps == [14 * 3600]
        assert len(backup.existing()) == 1

    def test_a_failure_is_reported_and_retried_after_a_full_interval(self, tmp_path: Path, clock: Clock) -> None:
        reported: list[str] = []

        async def on_error(message: str) -> None:
            reported.append(message)

        backup = DatabaseBackup(tmp_path / "missing.db", tmp_path / "backups", 3, clock)

        sleeps = self.run_loop(backup, timedelta(hours=6), rounds=2, on_error=on_error)

        assert len(reported) == 1 and "database not found" in reported[0]
        assert sleeps == [0, 6 * 3600]

    def test_a_failure_without_a_handler_does_not_stop_the_loop(self, tmp_path: Path, clock: Clock) -> None:
        backup = DatabaseBackup(tmp_path / "missing.db", tmp_path / "backups", 3, clock)

        assert self.run_loop(backup, timedelta(hours=6), rounds=2) == [0, 6 * 3600]

    def test_a_second_start_does_not_make_a_second_task(self, source: Path, clock: Clock) -> None:
        async def main() -> int:
            scheduler = BackupScheduler(backup_of(source, clock), timedelta(hours=24))
            scheduler.start()
            scheduler.start()
            await asyncio.sleep(0.05)
            count = sum(1 for t in asyncio.all_tasks() if t.get_name() == "database-backups")
            await scheduler.stop()
            return count

        assert asyncio.run(main()) == 1

    def test_stop_ends_the_task_and_is_safe_twice(self, source: Path, clock: Clock) -> None:
        async def main() -> bool:
            scheduler = BackupScheduler(backup_of(source, clock), timedelta(hours=24))
            scheduler.start()
            scheduler.start()  # a second start changes nothing
            await asyncio.sleep(0.05)
            await scheduler.stop()
            await scheduler.stop()
            return scheduler._task is None

        assert asyncio.run(main())


# --- inside the app -------------------------------------------------------------------------


def wait_for(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


class TestInTheApp:
    def test_a_backup_is_made_at_startup_when_enabled(self, client_factory) -> None:
        client = client_factory(backup=BackupSettings(enabled=True, keep=3, every_hours=24))
        folder = client.app.state.settings.backup_dir

        wait_for(lambda: folder.exists() and any(folder.glob("test-*.db")))

        (backup,) = folder.glob("test-*.db")
        with closing(sqlite3.connect(backup)) as conn:
            assert conn.execute("SELECT count(*) FROM accounts").fetchone()[0] >= 1  # the bootstrap admin

    def test_the_scheduler_gets_the_configured_interval_and_keep(self, client_factory) -> None:
        client = client_factory(backup=BackupSettings(enabled=True, keep=3, every_hours=7))

        scheduler = client.app.state.backups

        assert scheduler._every == timedelta(hours=7)
        assert scheduler._backup._keep == 3
        assert scheduler._backup._folder == client.app.state.settings.backup_dir

    def test_the_scheduler_is_stopped_when_the_app_shuts_down(self, client_factory) -> None:
        client = client_factory(backup=BackupSettings(enabled=True, keep=3, every_hours=24))
        scheduler = client.app.state.backups
        assert scheduler._task is not None

        client.__exit__(None, None, None)

        assert scheduler._task is None

    def test_there_is_no_scheduler_when_disabled(self, client_factory) -> None:
        assert client_factory().app.state.backups is None

    def test_no_backup_is_made_when_disabled(self, client_factory) -> None:
        client = client_factory()
        time.sleep(0.3)

        assert not client.app.state.settings.backup_dir.exists()

    def test_a_restart_within_the_interval_makes_no_second_backup(self, client_factory) -> None:
        first = client_factory(backup=BackupSettings(enabled=True, keep=5, every_hours=24))
        folder = first.app.state.settings.backup_dir
        wait_for(lambda: any(folder.glob("test-*.db")))

        second = client_factory(backup=BackupSettings(enabled=True, keep=5, every_hours=24))
        time.sleep(0.5)

        assert len(list(folder.glob("test-*.db"))) == 1
        assert second is not first

    def test_a_failing_backup_is_written_to_the_error_log(self, client_factory, monkeypatch: pytest.MonkeyPatch) -> None:
        async def broken(self) -> Path:
            raise BackupError("disk full (fake)")

        monkeypatch.setattr(DatabaseBackup, "run", broken)
        client = client_factory(backup=BackupSettings(enabled=True, keep=3, every_hours=24))
        from tests.test_registration import as_admin

        as_admin(client)

        def logged() -> bool:
            rows = client.get("/api/logs/error", params={"actor": "server"}).json()
            return any(r["source"] == "backup" and "disk full (fake)" in r["message"] for r in rows)

        wait_for(logged)

    def test_the_app_shuts_down_cleanly_with_backups_on(self, client_factory) -> None:
        client = client_factory(backup=BackupSettings(enabled=True, keep=3, every_hours=24))

        assert client.get("/api/health").json() == {"status": "ok"}
        # client_factory closes every client at the end: a stuck task would hang there.


# --- settings and the command line ----------------------------------------------------------------


class TestSettings:
    def test_defaults(self) -> None:
        assert BackupSettings.from_config({}) == BackupSettings(enabled=True, keep=14, every_hours=24)

    def test_values_are_read(self) -> None:
        assert BackupSettings.from_config({"enabled": False, "keep": 5, "every_hours": 6}) == BackupSettings(False, 5, 6)

    @pytest.mark.parametrize("raw", [{"keep": 0}, {"every_hours": 0}, {"keep": -1}])
    def test_a_value_below_one_is_refused(self, raw: dict) -> None:
        with pytest.raises(ValueError):
            BackupSettings.from_config(raw)

    def test_the_folder_sits_next_to_the_database(self, tmp_path: Path) -> None:
        assert make_settings(tmp_path).backup_dir == tmp_path / "data" / "backups"

    def test_load_settings_reads_the_block(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import src.config as config

        (tmp_path / "config_app.json").write_text(json.dumps({"backup": {"keep": 3, "every_hours": 12}}), encoding="utf-8")
        monkeypatch.setattr(config, "CONFIGS_DIR", tmp_path)

        loaded = config.load_settings()

        assert (loaded.backup.keep, loaded.backup.every_hours, loaded.backup.enabled) == (3, 12, True)


class TestCommandLine:
    @pytest.fixture
    def settings(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
        import scripts.backup_db as cli

        settings = replace(make_settings(tmp_path), backup=BackupSettings(enabled=False, keep=2, every_hours=24))
        make_db(settings.database_path)
        monkeypatch.setattr(cli, "load_settings", lambda: settings)
        return settings

    def test_it_writes_a_backup_and_says_where(self, settings: Settings, capsys: pytest.CaptureFixture) -> None:
        assert backup_cli([]) == 0

        out = capsys.readouterr().out
        (written,) = settings.backup_dir.glob("test-*.db")
        assert str(written) in out

    def test_keep_comes_from_the_settings_or_the_option(self, settings: Settings) -> None:
        for _ in range(4):
            backup_cli(["--keep", "3"])
            time.sleep(1.05)  # names carry seconds

        assert len(list(settings.backup_dir.glob("test-*.db"))) == 3

    def test_it_reports_failure_with_a_nonzero_code(self, settings: Settings, capsys: pytest.CaptureFixture) -> None:
        settings.database_path.unlink()

        assert backup_cli([]) == 1
        assert "Backup failed: database not found" in capsys.readouterr().err

    def test_keep_below_one_is_refused(self, settings: Settings) -> None:
        with pytest.raises(SystemExit):
            backup_cli(["--keep", "0"])


# --- the config checks -------------------------------------------------------------------------------


def issues_for(tmp_path: Path, **changes) -> set[tuple[str, str]]:
    settings = replace(make_settings(tmp_path), **changes)
    (tmp_path / "config_app.json").write_text("{}", encoding="utf-8")
    return {(i.file + ":" + i.key) for i in collect_issues(settings)}


class TestDeploymentChecks:
    def test_a_local_dev_setup_raises_nothing_about_cookies(self, tmp_path: Path) -> None:
        found = issues_for(tmp_path, backup=BackupSettings())

        assert not any("cookie_secure" in f or "hsts" in f or "backup" in f for f in found)

    @pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "ember.example.org", "::"])
    def test_an_open_host_without_a_secure_cookie_is_flagged(self, tmp_path: Path, host: str) -> None:
        assert "config_app.json:cookie_secure" in issues_for(tmp_path, host=host)

    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "LOCALHOST", "::1", "[::1]", "127.1.2.3"])
    def test_a_loopback_host_is_fine(self, tmp_path: Path, host: str) -> None:
        assert "config_app.json:cookie_secure" not in issues_for(tmp_path, host=host)

    def test_a_secure_cookie_on_an_open_host_is_fine(self, tmp_path: Path) -> None:
        found = issues_for(tmp_path, host="0.0.0.0", cookie_secure=True)

        assert "config_app.json:cookie_secure" not in found

    def test_a_secure_cookie_without_hsts_is_flagged(self, tmp_path: Path) -> None:
        from src.config import SecuritySettings

        flagged = issues_for(tmp_path, cookie_secure=True, security=SecuritySettings(hsts_max_age=0))
        fine = issues_for(tmp_path, cookie_secure=True, security=SecuritySettings(hsts_max_age=31536000))

        assert "config_app.json:security.headers.hsts_max_age" in flagged
        assert "config_app.json:security.headers.hsts_max_age" not in fine

    def test_hsts_zero_alone_is_fine_on_http(self, tmp_path: Path) -> None:
        from src.config import SecuritySettings

        assert "config_app.json:security.headers.hsts_max_age" not in issues_for(
            tmp_path, cookie_secure=False, security=SecuritySettings(hsts_max_age=0)
        )

    def test_backups_off_is_flagged_and_on_is_not(self, tmp_path: Path) -> None:
        assert "config_app.json:backup.enabled" in issues_for(tmp_path, backup=BackupSettings(enabled=False))
        assert "config_app.json:backup.enabled" not in issues_for(tmp_path, backup=BackupSettings(enabled=True))

    def test_an_empty_internal_token_is_flagged(self, tmp_path: Path) -> None:
        empty = issues_for(tmp_path)  # conftest writes an empty token

        assert "secret_internal_api.env:INTERNAL_API_TOKEN" in empty

    def test_a_set_internal_token_is_fine(self, tmp_path: Path) -> None:
        make_settings(tmp_path, internal_token="s3cret-token-value")
        settings = replace(make_settings(tmp_path, internal_token="s3cret-token-value"))
        (tmp_path / "config_app.json").write_text("{}", encoding="utf-8")

        found = {i.file + ":" + i.key for i in collect_issues(settings)}

        assert "secret_internal_api.env:INTERNAL_API_TOKEN" not in found

    def test_the_token_value_never_appears_in_a_message(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, internal_token="s3cret-token-value")
        (tmp_path / "config_app.json").write_text("{}", encoding="utf-8")

        assert not any("s3cret-token-value" in i.message for i in collect_issues(settings))


class TestBackupBlockInTheFile:
    def issues(self, tmp_path: Path, block: object) -> set[tuple[str, str]]:
        settings = make_settings(tmp_path)
        (tmp_path / "config_app.json").write_text(json.dumps({"backup": block}), encoding="utf-8")
        return {(i.key, i.message) for i in collect_issues(settings) if i.key.startswith("backup")}

    def test_a_good_block_has_no_problem_of_its_own(self, tmp_path: Path) -> None:
        found = self.issues(tmp_path, {"enabled": True, "keep": 5, "every_hours": 12})

        assert found == {("backup.enabled", "is false: the database is not backed up automatically")} or found == set()

    @pytest.mark.parametrize(
        ("block", "key"),
        [({"keep": 0}, "backup.keep"), ({"keep": "x"}, "backup.keep"), ({"every_hours": -3}, "backup.every_hours"),
         ({"keep": True}, "backup.keep"), ({"enabled": "yes"}, "backup.enabled")],
    )
    def test_a_bad_value_is_named(self, tmp_path: Path, block: dict, key: str) -> None:
        assert key in {k for k, m in self.issues(tmp_path, block) if "backed up automatically" not in m}

    def test_a_block_that_is_not_an_object_is_named(self, tmp_path: Path) -> None:
        assert ("backup", "must be an object") in self.issues(tmp_path, [1])
