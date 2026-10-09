"""Optional live boundary test; the independent PDFMerger runs in its own interpreter."""
import asyncio
import os
from pathlib import Path
import socket
import subprocess
import time
from types import SimpleNamespace

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from starlette.applications import Starlette
from starlette.testclient import TestClient
from src import upload_routes

PDF_ROOT = Path(__file__).resolve().parents[2] / "PDFMerger" / "pdf_merger"
PDF_PYTHON = PDF_ROOT / ".venv_pdf_merger" / "Scripts" / "python.exe"

@pytest.mark.skipif(not PDF_PYTHON.exists(), reason="Independent PDFMerger checkout/venv required")
def test_uploaded_originals_can_be_inspected_and_merged(tmp_path, monkeypatch):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    server = tmp_path / "serve.py"
    server.write_text("""
from pathlib import Path
import pikepdf
from PIL import Image
import uvicorn
from src.app import create_app
from src.config import Settings
root = Path(__file__).parent
for name, widths in [('first.pdf', [100, 101]), ('second.pdf', [200])]:
    pdf = pikepdf.new()
    for width in widths: pdf.add_blank_page(page_size=(width, 300))
    pdf.save(root / name)
Image.new('RGB', (10, 10), 'red').save(root / 'photo.png')
settings = Settings(store_dir=root/'store', log_dir=root/'logs', internal_api_token='test-pdf-token', signing_key=b's'*32, public_base_url=BASE)
uvicorn.run(create_app(settings), host='127.0.0.1', port=PORT, log_level='error')
""".replace('BASE', repr(base)).replace('PORT', str(port)), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(PDF_ROOT)}
    process = subprocess.Popen([str(PDF_PYTHON), str(server)], cwd=tmp_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                if httpx.get(base + "/api/health").status_code == 200: break
            except httpx.HTTPError:
                pass
            assert process.poll() is None and time.monotonic() < deadline, "PDFMerger did not start"
            time.sleep(.1)
        config = SimpleNamespace(transport="http", url=base + "/mcp", forward_requester=True, headers={"X-Internal-Token": "test-pdf-token"})
        monkeypatch.setattr(upload_routes, "settings", SimpleNamespace(internal_api_token="ember-token", extensions_config_path="unused"))
        monkeypatch.setattr(upload_routes, "load_extension_config", lambda _, id_: config)
        app = Starlette(); upload_routes.install_upload_routes(app)
        headers = {"X-Internal-Token": "ember-token", "X-Requester-Username": "alice"}
        with TestClient(app) as client:
            uploads = []
            for name in ("first.pdf", "second.pdf", "photo.png"):
                response = client.post("/upload/pdf", headers=headers, files={"file": (name, (tmp_path/name).read_bytes())})
                assert response.status_code == 200, response.text
                uploads.append(response.json())
            config.headers["X-Internal-Token"] = "wrong-token"
            assert client.post("/upload/pdf", headers=headers, files={"file": ("a.pdf", (tmp_path/'first.pdf').read_bytes())}).status_code == 502
        trusted = {"X-Internal-Token": "test-pdf-token", "X-Requester-Username": "alice"}
        assert len(httpx.get(base + "/api/files", headers=trusted).json()) == 3
        assert httpx.get(base + "/api/files", headers={**trusted, "X-Requester-Username": "bob"}).json() == []

        async def use_tools():
            async with streamablehttp_client(base + "/mcp", headers=trusted) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    inspected = await session.call_tool("tool_pdf_inspect", {"file_ids": ",".join(f["file_id"] for f in uploads)})
                    assert not inspected.isError, inspected.content
                    assert [f["pages"] for f in inspected.structuredContent["files"]] == [2, 1, 1]
                    merged = await session.call_tool("tool_pdf_merge", {"plan": {"segments": [{"file_id": f["file_id"]} for f in uploads]}})
                    assert not merged.isError, merged.content
                    return merged.structuredContent
        merged = asyncio.run(use_tools())
        assert merged["pages"] == 4
        download = httpx.get(merged["download_url"])
        assert download.status_code == 200 and download.content.startswith(b"%PDF")
        output = tmp_path/'merged.pdf'; output.write_bytes(download.content)
        verify = subprocess.run([str(PDF_PYTHON), '-c', 'import pikepdf,sys; p=pikepdf.open(sys.argv[1]); assert [int(float(x.mediabox[2])) for x in p.pages[:3]] == [100,101,200]', str(output)], capture_output=True)
        assert verify.returncode == 0, verify.stderr.decode()
    finally:
        process.terminate()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired: process.kill(); process.wait()
