from __future__ import annotations

import pytest

from src.store.sniff import sniff_mime


@pytest.mark.parametrize(
    ("head", "mime"),
    [
        (b"%PDF-1.7\n...", "application/pdf"),
        (b"\xef\xbb\xbfjunk%PDF-1.4", "application/pdf"),
        (b"\xff\xd8\xff\xe0\x00\x10JFIF", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n\x00\x00", "image/png"),
        (b"GIF89a\x01\x00", "image/gif"),
        (b"II*\x00\x08\x00", "image/tiff"),
        (b"MM\x00*\x00\x00", "image/tiff"),
        (b"RIFF\x24\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"\x00\x00\x00\x18ftypheic\x00\x00", "image/heic"),
        (b"\x00\x00\x00\x18ftypmif1\x00\x00", "image/heic"),
    ],
)
def test_known_signatures(head, mime):
    assert sniff_mime(head) == mime


@pytest.mark.parametrize("head", [b"", b"hello world", b"PK\x03\x04docx", b"\x00\x00\x00\x18ftypmp42"])
def test_unknown_content_is_none(head):
    assert sniff_mime(head) is None
