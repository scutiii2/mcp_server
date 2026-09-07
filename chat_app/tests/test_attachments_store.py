"""Tests for chat_app's per-chat file attachment storage - see
src/services/attachments_store.py. Pure filesystem, no Flask app
needed - every test uses tmp_path as the attachments_dir directly."""

from __future__ import annotations

import pytest

from src.services import attachments_store


def test_save_attachment_writes_the_file_and_returns_its_metadata(tmp_path):
    result = attachments_store.save_attachment(tmp_path, "chat1", "notes.txt", b"hello world", max_file_size_mb=5)

    assert result == {"filename": "notes.txt", "size": 11}
    assert (tmp_path / "chat1" / "notes.txt").read_text(encoding="utf-8") == "hello world"


def test_save_attachment_rejects_a_file_over_the_size_cap(tmp_path):
    with pytest.raises(attachments_store.AttachmentError):
        attachments_store.save_attachment(tmp_path, "chat1", "big.txt", b"x" * 100, max_file_size_mb=0.00005)


def test_save_attachment_rejects_non_utf8_data(tmp_path):
    with pytest.raises(attachments_store.AttachmentError):
        attachments_store.save_attachment(tmp_path, "chat1", "bin.dat", b"\xff\xfe\x00\x01", max_file_size_mb=5)


def test_save_attachment_rejects_a_path_traversal_filename(tmp_path):
    with pytest.raises(attachments_store.AttachmentError):
        attachments_store.save_attachment(tmp_path, "chat1", "../../etc/passwd", b"data", max_file_size_mb=5)


def test_save_attachment_rejects_a_filename_with_a_backslash(tmp_path):
    with pytest.raises(attachments_store.AttachmentError):
        attachments_store.save_attachment(tmp_path, "chat1", "sub\\evil.txt", b"data", max_file_size_mb=5)


def test_list_attachments_is_empty_for_an_unknown_chat(tmp_path):
    assert attachments_store.list_attachments(tmp_path, "nope") == []


def test_list_attachments_returns_sorted_filename_and_size(tmp_path):
    attachments_store.save_attachment(tmp_path, "chat1", "b.txt", b"22", max_file_size_mb=5)
    attachments_store.save_attachment(tmp_path, "chat1", "a.txt", b"1", max_file_size_mb=5)

    assert attachments_store.list_attachments(tmp_path, "chat1") == [
        {"filename": "a.txt", "size": 1},
        {"filename": "b.txt", "size": 2},
    ]


def test_read_attachment_text_returns_none_for_a_missing_file(tmp_path):
    assert attachments_store.read_attachment_text(tmp_path, "chat1", "nope.txt") is None


def test_read_attachment_text_returns_none_for_a_traversal_filename(tmp_path):
    assert attachments_store.read_attachment_text(tmp_path, "chat1", "../secret.txt") is None


def test_read_attachment_text_round_trips_saved_content(tmp_path):
    attachments_store.save_attachment(tmp_path, "chat1", "notes.txt", b"content here", max_file_size_mb=5)

    assert attachments_store.read_attachment_text(tmp_path, "chat1", "notes.txt") == "content here"


def test_delete_attachment_removes_the_file_and_returns_true(tmp_path):
    attachments_store.save_attachment(tmp_path, "chat1", "notes.txt", b"data", max_file_size_mb=5)

    assert attachments_store.delete_attachment(tmp_path, "chat1", "notes.txt") is True
    assert not (tmp_path / "chat1" / "notes.txt").exists()


def test_delete_attachment_returns_false_for_a_missing_file(tmp_path):
    assert attachments_store.delete_attachment(tmp_path, "chat1", "nope.txt") is False


def test_delete_chat_attachments_removes_the_whole_folder(tmp_path):
    attachments_store.save_attachment(tmp_path, "chat1", "a.txt", b"1", max_file_size_mb=5)
    attachments_store.save_attachment(tmp_path, "chat2", "b.txt", b"2", max_file_size_mb=5)

    attachments_store.delete_chat_attachments(tmp_path, "chat1")

    assert not (tmp_path / "chat1").exists()
    assert (tmp_path / "chat2" / "b.txt").exists()


def test_delete_chat_attachments_is_a_no_op_for_an_unknown_chat(tmp_path):
    attachments_store.delete_chat_attachments(tmp_path, "nope")  # must not raise
