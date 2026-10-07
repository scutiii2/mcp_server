"""Tests for WatchSpec validation, normalisation and check dispatch."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.capabilities.watchers.utils.checks import CheckResult
from src.capabilities.watchers.utils.spec import WatchSpec, build_spec, run_check


def spec(**changes) -> WatchSpec:
    values = dict(kind="url", target="https://example.com/", expect="up", contains="", label="", owner="alice", email="a@x.io")
    return WatchSpec(**{**values, **changes})


def test_build_spec_normalises_kind_expect_and_trims():
    built = build_spec(" URL ", " https://example.com/ ", " Down ", "", " my site ", "alice", "a@x.io")

    assert (built.kind, built.target, built.expect, built.label) == ("url", "https://example.com/", "down", "my site")


def test_build_spec_refuses_bad_input_naming_the_choices():
    with pytest.raises(ValueError, match="url, app, tcp"):
        build_spec("ping", "x", "up", "", "", "alice", "")
    with pytest.raises(ValueError, match="up, down"):
        build_spec("url", "https://example.com/", "sideways", "", "", "alice", "")
    with pytest.raises(ValueError, match="only http and https"):
        build_spec("url", "ftp://x", "up", "", "", "alice", "")
    with pytest.raises(ValueError, match="host:port"):
        build_spec("tcp", "nohost", "up", "", "", "alice", "")
    with pytest.raises(ValueError, match="app name"):
        build_spec("app", "bad name", "up", "", "", "alice", "")
    with pytest.raises(ValueError, match="contains"):
        build_spec("tcp", "host:80", "up", "text", "", "alice", "")
    with pytest.raises(ValueError, match="contains"):
        build_spec("url", "https://example.com/", "down", "text", "", "alice", "")
    with pytest.raises(ValueError, match="at most 100"):
        build_spec("url", "https://example.com/", "up", "x" * 101, "", "alice", "")
    with pytest.raises(ValueError, match="at most 60"):
        build_spec("url", "https://example.com/", "up", "", "x" * 61, "alice", "")


def test_detail_round_trip_and_title():
    original = spec(label="Blog")

    assert WatchSpec.from_detail(original.to_detail()) == original
    assert WatchSpec.from_detail({}) == WatchSpec("", "", "", "", "", "", "")
    assert original.title() == "Blog" and spec().title() == "https://example.com/"


def test_condition_text_reads_naturally():
    assert spec().condition_text() == "https://example.com/ to be reachable"
    assert spec(contains="ready").condition_text() == "https://example.com/ to be reachable and contain 'ready'"
    assert spec(expect="down").condition_text() == "https://example.com/ to be unreachable"
    assert spec(kind="app", target="web").condition_text() == "app web to be running"
    assert spec(kind="tcp", target="h:22", expect="down").condition_text() == "h:22 to be closed"


def test_run_check_dispatches_by_kind(monkeypatch):
    from src.capabilities.watchers.utils import spec as spec_module

    calls = []
    monkeypatch.setattr(spec_module.checks, "check_url", lambda url, contains="": calls.append(("url", url, contains)) or CheckResult(True, {}))
    monkeypatch.setattr(spec_module.checks, "check_tcp", lambda host, port: calls.append(("tcp", host, port)) or CheckResult(False, {}))

    assert run_check(spec(contains="ok")).up is True
    assert run_check(spec(kind="tcp", target="[::1]:8080")).up is False
    apps = lambda: SimpleNamespace(apps=[SimpleNamespace(name="web", status="running")])
    assert run_check(spec(kind="app", target="web"), list_apps=apps).up is True
    assert calls == [("url", "https://example.com/", "ok"), ("tcp", "::1", 8080)]


CONTROL_CHARACTERS = ["a" + chr(13) + chr(10) + "Bcc: x", "tab" + chr(9) + "here", "nul" + chr(0), "del" + chr(127)]


@pytest.mark.parametrize("field", ["label", "contains", "target"])
@pytest.mark.parametrize("bad", CONTROL_CHARACTERS)
def test_build_spec_rejects_control_characters(field, bad):
    values = dict(kind="url", target="https://example.com/", expect="up", contains="", label="")
    values[field] = values[field] + bad

    with pytest.raises(ValueError, match="control characters"):
        build_spec(values["kind"], values["target"], values["expect"], values["contains"], values["label"], "alice", "a@x.io")
