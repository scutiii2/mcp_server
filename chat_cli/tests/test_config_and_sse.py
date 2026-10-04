"""The settings file and the event-stream parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import CliConfig, ConfigError, DEFAULT_URL, load_config
from src.sse import SseParser


def write(path: Path, data) -> Path:
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


class TestConfig:
    def test_defaults_when_there_is_no_file_and_no_example(self, tmp_path: Path) -> None:
        assert load_config(tmp_path / "config_cli.json") == CliConfig(DEFAULT_URL, "")

    def test_the_first_run_copies_the_example(self, tmp_path: Path) -> None:
        write(tmp_path / "config_cli.json.example", {"ember_api_url": "http://example:1", "username": "ada"})

        config = load_config(tmp_path / "config_cli.json")

        assert config == CliConfig("http://example:1", "ada")
        assert (tmp_path / "config_cli.json").is_file()

    def test_a_real_file_wins_over_the_example(self, tmp_path: Path) -> None:
        write(tmp_path / "config_cli.json.example", {"username": "example"})
        write(tmp_path / "config_cli.json", {"username": "mine"})

        assert load_config(tmp_path / "config_cli.json").username == "mine"

    def test_a_trailing_slash_and_spaces_are_cleaned(self, tmp_path: Path) -> None:
        write(tmp_path / "c.json", {"ember_api_url": "https://ember.example/", "username": "  ada "})

        assert load_config(tmp_path / "c.json") == CliConfig("https://ember.example", "ada")

    def test_missing_keys_take_the_defaults(self, tmp_path: Path) -> None:
        assert load_config(write(tmp_path / "c.json", {})) == CliConfig()

    @pytest.mark.parametrize("text", ["{not json", "[]", '"text"', "null"])
    def test_a_file_that_is_not_an_object_is_refused_naming_the_file(self, tmp_path: Path, text: str) -> None:
        path = write(tmp_path / "c.json", text)

        with pytest.raises(ConfigError, match="c.json"):
            load_config(path)

    @pytest.mark.parametrize("url", ["ember", "ftp://x", "", 5, None])
    def test_the_address_must_be_http_or_https(self, tmp_path: Path, url) -> None:
        with pytest.raises(ConfigError, match="ember_api_url"):
            load_config(write(tmp_path / "c.json", {"ember_api_url": url}))

    def test_the_username_must_be_text(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="username"):
            load_config(write(tmp_path / "c.json", {"username": 7}))

    def test_the_real_example_file_is_valid(self) -> None:
        example = Path(__file__).resolve().parents[1] / "configs" / "config_cli.json.example"

        assert load_config(example).ember_api_url == DEFAULT_URL


class TestSse:
    def event(self, n: int, **extra) -> str:
        return f"id: {n}\ndata: {json.dumps({'sequence': n, **extra})}\n\n"

    def test_one_event(self) -> None:
        assert SseParser().feed(self.event(1, type="token", text="a")) == [{"sequence": 1, "type": "token", "text": "a"}]

    def test_several_events_in_one_chunk(self) -> None:
        events = SseParser().feed(self.event(1) + self.event(2) + self.event(3))

        assert [e["sequence"] for e in events] == [1, 2, 3]

    def test_an_event_in_pieces_waits_until_it_is_whole(self) -> None:
        parser, whole = SseParser(), self.event(1, type="token")

        assert parser.feed(whole[:5]) == []
        assert parser.feed(whole[5:-1]) == []
        assert [e["sequence"] for e in parser.feed(whole[-1:])] == [1]

    def test_a_cut_inside_the_blank_line_between_events(self) -> None:
        parser, first = SseParser(), self.event(1)

        assert parser.feed(first[:-1]) == []
        assert [e["sequence"] for e in parser.feed(first[-1:] + self.event(2))] == [1, 2]

    def test_a_ping_is_skipped(self) -> None:
        assert [e["sequence"] for e in SseParser().feed(": ping\n\n" + self.event(1) + ": ping\n\n")] == [1]

    def test_data_lines_are_joined_with_a_newline(self) -> None:
        text = 'id: 4\ndata: {"sequence": 4,\ndata: "type": "final"}\n\n'

        assert SseParser().feed(text) == [{"sequence": 4, "type": "final"}]

    def test_windows_line_ends_work_too(self) -> None:
        assert [e["sequence"] for e in SseParser().feed(self.event(1).replace("\n", "\r\n"))] == [1]

    def test_a_data_line_without_the_space_after_the_colon_works_too(self) -> None:
        assert SseParser().feed('data:{"sequence": 1}\n\n') == [{"sequence": 1}]

    def test_only_one_space_after_the_colon_is_dropped(self) -> None:
        assert SseParser().feed('data:  {"sequence": 1}\n\n') == [{"sequence": 1}]

    def test_an_extra_blank_line_between_events_is_harmless(self) -> None:
        assert [e["sequence"] for e in SseParser().feed(self.event(1) + "\n" + self.event(2))] == [1, 2]

    def test_bad_json_raises(self) -> None:
        with pytest.raises(ValueError):
            SseParser().feed("data: {nope\n\n")

    def test_an_event_that_is_not_an_object_raises(self) -> None:
        with pytest.raises(ValueError, match="not an object"):
            SseParser().feed("data: [1, 2]\n\n")


class TestTitle:
    def test_a_title_of_exactly_60_characters_is_not_cut(self) -> None:
        from src.session import title_from

        assert title_from("t" * 60) == "t" * 60
        assert title_from("t" * 61) == "t" * 59 + "\u2026"
