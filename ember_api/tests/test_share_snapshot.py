from __future__ import annotations

from src.services.share_service import hash_token, snapshot_messages

FILE = '[[ATTACHMENT filename="report.txt" chars="9" truncated="false"]]\nsecretword\n[[/ATTACHMENT]]'


def test_keeps_plain_questions_and_answers_as_role_and_content_only() -> None:
    messages = [
        {"role": "user", "content": "q1"},
        {
            "role": "assistant",
            "content": "a1",
            "model": "claude",
            "total_tokens": 10,
            "input_tokens": 7,
            "duration_s": 1.0,
            "steps": [{"tool": "t", "arguments": {"password": "hunter2"}, "result": "secret output"}],
        },
    ]

    assert snapshot_messages(messages) == [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]


def test_leaves_out_summaries_raw_logs_and_command_results() -> None:
    messages = [
        {"role": "assistant", "kind": "summary", "content": "S"},
        {"role": "assistant", "kind": "log_attachment", "content": "raw log with everything"},
        {"role": "user", "kind": "command", "content": "/apps start"},
        {"role": "assistant", "kind": "command", "content": "tool output"},
        {"role": "user", "content": "kept"},
    ]

    assert snapshot_messages(messages) == [{"role": "user", "content": "kept"}]


def test_replaces_attached_file_text_with_its_name() -> None:
    messages = [{"role": "user", "content": f"please summarize\n\n{FILE}\n\n{FILE.replace('report', 'notes')}"}]

    shared = snapshot_messages(messages)

    assert shared == [{"role": "user", "content": "please summarize\n\n📎 report.txt\n\n📎 notes.txt"}]
    assert "secretword" not in shared[0]["content"]


def test_a_question_that_was_only_a_file_keeps_the_file_name() -> None:
    assert snapshot_messages([{"role": "user", "content": FILE}]) == [{"role": "user", "content": "📎 report.txt"}]


def test_strips_download_markers_from_answers() -> None:
    answer = 'Done.\n[[DOWNLOAD filename="out.csv" bytes="10" url="/internal/files/abc"]]'

    assert snapshot_messages([{"role": "assistant", "content": answer}]) == [{"role": "assistant", "content": "Done."}]


def test_leaves_out_failed_and_interrupted_answers() -> None:
    messages = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "error: provider is down at http://10.0.0.5:9100"},
        {"role": "assistant", "content": "  error: still down"},
        {"role": "assistant", "content": "partial text\n\n⚠️ Interrupted: ember_api stopped before the answer finished."},
        {"role": "assistant", "content": "⚠️ Interrupted: ember_api stopped before the answer finished."},
        {"role": "assistant", "content": "An answer that mentions an error: and goes on"},
    ]

    shared = snapshot_messages(messages)

    assert [m["content"] for m in shared] == [
        "q",
        "partial text\n\n⚠️ Interrupted: ember_api stopped before the answer finished.",
        "An answer that mentions an error: and goes on",
    ]


def test_drops_messages_that_end_up_empty_and_ones_that_are_not_text() -> None:
    messages = [
        {"role": "user", "content": "   "},
        {"role": "assistant", "content": '[[DOWNLOAD filename="a" bytes="1" url="/x"]]'},
        {"role": "system", "content": "not a chat role"},
        {"role": "user", "content": 5},
        {"role": "user"},
        {"role": "user", "content": "ok"},
    ]

    assert snapshot_messages(messages) == [{"role": "user", "content": "ok"}]


def test_does_not_change_its_input() -> None:
    messages = [{"role": "user", "content": FILE, "kind": None}]
    before = [dict(m) for m in messages]

    snapshot_messages(messages)

    assert messages == before


def test_token_hash_is_a_stable_sha256_hex() -> None:
    assert hash_token("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
