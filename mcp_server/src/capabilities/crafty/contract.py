"""Shapes for the crafty-world tools.

``WorldInfo`` (and every other result here) deliberately has no
``api_token`` field, on the same footing as ``otp/contract.py``'s
``RequestOtpResult`` deliberately having no ``code`` field: the token is
a credential, ``infra/crafty_registry.py`` is the only thing that reads
it back, and a result type that carried it would hand it to whatever
model called ``crafty_world_list_tool``.

One result type per action, each carrying a ``message`` (or ``report``)
field meant to be relayed to a person verbatim - same convention as
``server_manager/contract.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorldInfo(BaseModel):
    name: str = Field(description="The label this world was registered under.")
    base_url: str = Field(description="The Crafty Controller instance this world lives on.")
    server_id: str = Field(description="The server id Crafty knows this world as.")
    verify_ssl: bool = Field(description="Whether this world's Crafty connection verifies TLS certs.")


class WorldListResult(BaseModel):
    worlds: list[WorldInfo] = Field(description="Every registered world.")
    report: str = Field(
        description="Human-readable table of the same data, safe to relay verbatim."
    )


class DefaultBaseUrlResult(BaseModel):
    base_url: str = Field(description="The Crafty Controller instance now used as the default.")
    verify_ssl: bool = Field(description="Whether the default connection verifies TLS certs.")
    message: str = Field(description="Human-readable confirmation, safe to relay verbatim.")


class PingBaseUrlResult(BaseModel):
    base_url: str = Field(description="The Crafty Controller URL that was pinged.")
    reachable: bool = Field(description="Whether anything answered at that URL.")
    status_code: int | None = Field(default=None, description="HTTP status code returned, if it answered.")
    latency_ms: float | None = Field(default=None, description="Round-trip time in milliseconds, if reachable.")
    error: str | None = Field(default=None, description="Why the ping failed, if it was not reachable.")
    message: str = Field(description="Human-readable summary, safe to relay verbatim.")


class WorldRegisterResult(BaseModel):
    name: str = Field(description="The world name that was registered.")
    base_url: str = Field(description="The Crafty Controller instance it was registered against.")
    server_id: str = Field(description="The server id it was registered with.")
    message: str = Field(description="Human-readable confirmation, safe to relay verbatim.")


class WorldRemoveResult(BaseModel):
    name: str = Field(description="The world that was removed.")
    message: str = Field(description="Human-readable confirmation, safe to relay verbatim.")


class WorldActionResult(BaseModel):
    name: str = Field(description="The world that was acted on.")
    action: str = Field(description="Which action ran: start, stop, or restart.")
    message: str = Field(description="Human-readable confirmation, safe to relay verbatim.")


class WorldCommandResult(BaseModel):
    name: str = Field(description="The world the command was sent to.")
    command: str = Field(description="The console command that was sent.")
    message: str = Field(description="Human-readable confirmation, safe to relay verbatim.")


class WorldStatusResult(BaseModel):
    name: str = Field(description="The world that was checked.")
    running: bool | None = Field(description="Whether the world's server process is running.")
    online: int = Field(description="Current player count.")
    max: int = Field(description="Configured player slot limit.")
    players: list[str] = Field(description="Names of players currently online.")
    version: str = Field(description="The Minecraft server version, or 'Unknown'.")
    cpu: float | None = Field(default=None, description="CPU usage percent, when Crafty reports one.")
    mem: str | None = Field(default=None, description="Memory in use, human-readable (e.g. '1.00 GB').")
    world_name: str | None = Field(default=None, description="The active in-game world/level name.")
    report: str = Field(description="Human-readable summary, safe to relay verbatim.")
