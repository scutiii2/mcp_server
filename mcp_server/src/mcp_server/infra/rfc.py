"""SAP RFC connection helper - thin wrapper for pyrfc.Connection.

``pyrfc`` requires SAP's proprietary NW RFC SDK to even install - it's
not a plain ``pip install`` the way ``hdbcli`` is; you need SAP's
compiled library files, gated behind SAP support portal access. This is
the heaviest dependency in this scaffold. Deferred import here, matching
the pattern used for ``sap_ai_hub_provider.py``'s ``gen_ai_hub`` import -
nothing else breaks if ``pyrfc`` isn't installed, only functions that
actually call ``open_rfc_connection()`` do.
"""

from __future__ import annotations

from typing import Any, Protocol

from mcp_server.infra.sap_config import RfcServerConfig


class RfcConnection(Protocol):
    """Just enough of pyrfc.Connection's interface for domain functions to
    depend on - lets tests pass a fake object with a `.call()`/`.close()`
    method, no pyrfc import needed anywhere outside this file and
    open_rfc_connection(). Shared by every RFC-based capability
    (dumps/, jobs/) rather than each redefining its own copy."""

    def call(self, function_name: str, **kwargs: Any) -> dict[str, Any]: ...
    def close(self) -> None: ...


def open_rfc_connection(server: RfcServerConfig) -> Any:
    from pyrfc import Connection

    return Connection(
        ashost=server.ashost,
        sysnr=server.sysnr,
        client=server.client,
        user=server.user,
        passwd=server.passwd,
        lang=server.lang,
    )
