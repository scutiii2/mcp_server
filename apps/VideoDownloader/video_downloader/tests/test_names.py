from src.store.names import content_disposition, mime_for, safe_filename


def test_safe_filename_strips_paths_and_unsafe_chars():
    assert safe_filename("../../etc/pa:ss*wd.mp4", "video") == "pa_ss_wd.mp4"
    assert safe_filename("", "video") == "video"
    assert safe_filename(None, "video") == "video"
    assert safe_filename("a" * 400 + ".mp4", "video") == "a" * 150


def test_content_disposition_has_ascii_fallback_and_utf8_name():
    header = content_disposition("café.mp4")
    assert header.startswith("attachment;")
    assert 'filename="caf.mp4"' in header
    assert "filename*=UTF-8''caf%C3%A9.mp4" in header
    assert content_disposition("a.mp4", inline=True).startswith("inline;")


def test_mime_for():
    assert mime_for(".mp4") == "video/mp4"
    assert mime_for(".MP3") == "audio/mpeg"
    assert mime_for(".m4a") == "audio/mp4"
    assert mime_for(".webm") == "video/webm"
    assert mime_for(".xyz") == "application/octet-stream"
