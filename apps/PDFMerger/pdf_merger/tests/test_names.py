from __future__ import annotations

from src.store.names import content_disposition, ensure_pdf_suffix, file_stem, safe_filename


def test_safe_filename_strips_paths_and_odd_characters():
    assert safe_filename("../../etc/passwd", "x") == "passwd"
    assert safe_filename("C:\\Users\\me\\scan 01.jpg", "x") == "scan 01.jpg"
    assert safe_filename('bad<>:"|?*name.pdf', "x") == "bad_name.pdf"
    assert safe_filename("résumé.pdf", "x") == "résumé.pdf"


def test_safe_filename_falls_back_to_default():
    assert safe_filename(None, "upload") == "upload"
    assert safe_filename("  ...  ", "upload") == "upload"


def test_ensure_pdf_suffix():
    assert ensure_pdf_suffix("merged") == "merged.pdf"
    assert ensure_pdf_suffix("merged.PDF") == "merged.PDF"


def test_file_stem():
    assert file_stem("contract_2026.pdf") == "contract_2026"
    assert file_stem("noext") == "noext"


def test_content_disposition_has_ascii_and_utf8_forms():
    header = content_disposition("résumé.pdf")
    assert header.startswith('attachment; filename="rsum.pdf"')
    assert "filename*=UTF-8''r%C3%A9sum%C3%A9.pdf" in header
    assert content_disposition("a.pdf", inline=True).startswith("inline;")
