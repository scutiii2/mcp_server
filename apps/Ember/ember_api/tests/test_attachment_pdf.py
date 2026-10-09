import base64
import httpx
from tests.test_registration import as_admin

FILE = {"file_id": "f_scan", "pages": 2, "kind": "pdf", "expires_at": 2000000000}

def post(client, filename="scan.pdf", content=b"%PDF-scan"):
    return client.post("/api/attachments/pdf", json={"filename": filename, "data": base64.b64encode(content).decode()})

def test_original_upload_does_not_require_extractable_text(client, upstream):
    upstream.handler = lambda request: httpx.Response(200, json=FILE)
    as_admin(client)
    response = post(client, "C:\\docs\\scan.pdf")
    assert response.status_code == 200, response.text
    assert response.json()["file_id"] == "f_scan"
    assert response.json()["filename"] == "scan.pdf" and response.json()["text"] == ""
    sent = upstream.requests[-1]
    assert sent.url.path == "/upload/pdf" and sent.headers["x-requester-username"] == "root"
    assert b'%PDF-scan' in sent.content and b'filename="scan.pdf"' in sent.content
    assert sent.extensions["timeout"]["read"] == 120

def test_image_attachment_is_stored_without_text_extraction(client, upstream):
    upstream.handler = lambda request: httpx.Response(200, json={**FILE, "kind": "image"})
    as_admin(client)
    response = post(client, "image.png", b"image")
    assert response.status_code == 200 and response.json()["kind"] == "image"

def test_login_required(client):
    assert post(client).status_code == 401

def test_input_errors_never_reach_upstream(client, upstream):
    as_admin(client)
    assert post(client, "file.exe").status_code == 400
    assert client.post("/api/attachments/pdf", json={"filename": "a.pdf", "data": "??"}).status_code == 400
    assert not upstream.requests

def test_unavailable_or_invalid_metadata_is_reported(client, upstream):
    as_admin(client)
    upstream.handler = lambda request: httpx.Response(200, json={"file_id": "f_1"})
    assert post(client).status_code == 502
    upstream.unreachable = True
    assert post(client).status_code == 502

def test_pdf_refusal_is_visible(client, upstream):
    as_admin(client)
    upstream.handler = lambda request: httpx.Response(400, json={"error": "Encrypted PDF"})
    response = post(client)
    assert response.status_code == 400 and "Encrypted PDF" in response.json()["detail"]


def test_successful_pdf_upload_retains_its_optional_preview(client, upstream, monkeypatch):
    from types import SimpleNamespace
    from src.routes import attachments
    async def extract(filename, content):
        return SimpleNamespace(text="PDF text preview", char_count=16, truncated=True)
    monkeypatch.setattr(attachments, "extract_text_async", extract)
    upstream.handler = lambda request: httpx.Response(200, json=FILE)
    as_admin(client)
    result = post(client).json()
    assert result["text"] == "PDF text preview" and result["truncated"] is True
    assert result["file_id"] == "f_scan"
