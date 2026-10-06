"""End-to-end test: real scanner -> JSON cache -> registry -> HTTP.

Every other test suite in this project mocks at least one layer boundary
(registry tests mock the scanner; route tests mock the registry). This
test is the only one that exercises the full pipeline with the real
scanner and the real registry, so a CatalogEntry's shape is verified all
the way through to the locked HTTP schema. This is the gap that let
Finding 1 (a decorated method wrongly double-counted as a bogus top-level
entry) slip through every existing test.
"""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.testclient import TestClient

from src import registry
from src.routes import install_catalog_routes


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_real_scanner_to_cache_to_registry_to_http(tmp_path, monkeypatch):
    # 1. Fake project source tree.
    src_root = tmp_path / "demo" / "src"
    _write(
        src_root / "services" / "greeter.py",
        "from src.utils.catalog import catalog\n\n"
        "@catalog\n"
        "def greet(name: str, times: int = 1):\n"
        "    'Greets someone, optionally more than once.'\n"
        "    return name * times\n\n\n"
        "@catalog\n"
        "class Greeter:\n"
        "    'Says hello politely.'\n\n"
        "    def __init__(self, language: str = 'en'):\n"
        "        self.language = language\n\n"
        "    def say_hello(self, name):\n"
        "        return f'hello {name}'\n\n"
        "    @catalog\n"
        "    def _internal_helper(self):\n"
        "        # decorated but private - still catalogued (its own\n"
        "        # namespaced entry), same as a decorated module-level\n"
        "        # function isn't excluded for a leading underscore either.\n"
        "        # Must NOT leak into `methods` (still public-only) or as a\n"
        "        # bogus flat top-level entry (Finding 1's regression).\n"
        "        pass\n",
    )

    # Reset registry module state (module-level globals, shared across tests).
    registry._entries = []
    registry._status = "scanning"

    cache_path = tmp_path / "cache.json"

    # 2. Run the real scan -> cache -> registry pipeline synchronously
    # (call _run_refresh directly to avoid waiting on a background thread).
    registry._run_refresh([("demo", src_root)], cache_path)

    try:
        status, entries = registry.current()
        assert status == "ready"
        assert cache_path.exists()

        by_id = {entry["id"]: entry for entry in entries}
        assert set(by_id) == {
            "demo.src.services.greeter.greet",
            "demo.src.services.greeter.Greeter",
            "demo.src.services.greeter.Greeter._internal_helper",
        }

        # 3/4. Build the Starlette app and hit it over real HTTP.
        app = Starlette()
        install_catalog_routes(app)
        with TestClient(app) as client:
            response = client.get("/catalog")
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "ready"
            assert len(body["entries"]) == 3

            func_entry = by_id["demo.src.services.greeter.greet"]
            assert func_entry == {
                "id": "demo.src.services.greeter.greet",
                "type": "function",
                "name": "greet",
                "description": "Greets someone, optionally more than once.",
                "project": "demo",
                "file": "src/services/greeter.py",
                "line": 3,
                "parameters": [
                    {"name": "name", "annotation": "str", "default": None},
                    {"name": "times", "annotation": "int", "default": "1"},
                ],
            }
            assert "methods" not in func_entry

            class_entry = by_id["demo.src.services.greeter.Greeter"]
            assert class_entry["type"] == "class"
            assert class_entry["name"] == "Greeter"
            assert class_entry["description"] == "Says hello politely."
            assert class_entry["parameters"] == [
                {"name": "language", "annotation": "str", "default": "'en'"}
            ]
            # `methods` still lists only the public method - not __init__,
            # not the underscore-prefixed one, even though the latter is
            # separately catalogued below.
            assert class_entry["methods"] == ["say_hello"]

            method_entry = by_id["demo.src.services.greeter.Greeter._internal_helper"]
            assert method_entry["type"] == "method"
            assert method_entry["name"] == "_internal_helper"
            # `self` dropped, and it's namespaced under its class - never a
            # bogus flat top-level entry (Finding 1's original regression).
            assert method_entry["parameters"] == []
            assert len(by_id) == 3

            # 5. GET /catalog/{id} finds each entry by its id.
            for entry_id in by_id:
                response = client.get(f"/catalog/{entry_id}")
                assert response.status_code == 200
                assert response.json()["id"] == entry_id

            response = client.get("/catalog/does.not.exist")
            assert response.status_code == 404
    finally:
        registry._entries = []
        registry._status = "scanning"
