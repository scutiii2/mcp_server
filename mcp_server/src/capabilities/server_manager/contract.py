"""Shapes for the server-manager tools.

One result type per action, all carrying a `message` field meant to be
relayed to a person verbatim - same convention as `otp/contract.py` and
`host_health/contract.py`, so a model doesn't have to invent wording for
"I stopped it" out of a bare status code.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AppInfo(BaseModel):
    name: str = Field(description="The container's name, as Docker knows it.")
    status: str = Field(
        description="Docker's own status word: running, exited, paused, restarting, etc."
    )
    image: str = Field(description="The image the container was created from.")


class AppListResult(BaseModel):
    apps: list[AppInfo] = Field(description="Every container on this host, running or not.")
    report: str = Field(
        description="Human-readable table of the same data, safe to relay verbatim."
    )


class AppActionResult(BaseModel):
    name: str = Field(description="The container that was acted on.")
    action: str = Field(description="Which action ran: start, stop, or restart.")
    status: str = Field(description="The container's Docker status after the action ran.")
    message: str = Field(description="Human-readable confirmation, safe to relay verbatim.")
