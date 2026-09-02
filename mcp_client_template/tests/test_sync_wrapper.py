from __future__ import annotations

import json
import sys
from pathlib import Path

from src.sync_wrapper import SyncMcpClient


def _write_config(tmp_path: Path) -> Path:
    # Absolute file path, not "-m src._fixtures.reference_server" - see
    # test_registry.py's test_real_fixture_server_end_to_end for why "-m"
    # doesn't work when pytest is launched from outside mcp_client_template/.
    fixture_path = Path(__file__).resolve().parent.parent / "src" / "_fixtures" / "reference_server.py"
    config_path = tmp_path / "config_servers.json"
    config_path.write_text(
        json.dumps(
            {
                "reference": {
                    "label": "Reference",
                    "description": "Dev fixture",
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": [str(fixture_path)],
                }
            }
        ),
        encoding="utf-8",
    )
    return config_path


def test_sync_client_connects_lists_and_calls_tools_from_a_plain_sync_test(tmp_path: Path):
    """No @pytest.mark.anyio here on purpose - the whole point of this
    module is that a synchronous caller never touches asyncio directly."""
    client = SyncMcpClient()
    try:
        statuses = client.connect_all(_write_config(tmp_path))
        assert [status.status for status in statuses] == ["connected"]

        names = {tool.name for tool in client.list_tools()}
        assert names == {"reference__echo", "reference__add"}

        result = client.call_tool("reference__add", {"a": 2, "b": 3})
        assert result.structuredContent == {"result": 5}
    finally:
        client.close()
