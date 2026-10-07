"""Request/result models for the server_manager tools. Every result ends
with a `message` meant to be relayed to a person verbatim."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AppInfo(BaseModel):
    name: str = Field(description="The container's name, as Docker knows it.")
    status: str = Field(description="Docker's own status word: running, exited, paused, restarting, etc.")
    image: str = Field(description="The image the container was created from.")


class AppListResult(BaseModel):
    apps: list[AppInfo] = Field(description="Every container on this host, running or not.")
    message: str = Field(description="Human-readable table of the same data, safe to relay verbatim.")


class AppLogsResult(BaseModel):
    name: str = Field(description="The container the log is from.")
    lines: int = Field(description="How many log lines the file holds.")
    download_markers: list[str] = Field(
        default_factory=list,
        description="Download cards for the log file; empty when nothing could be offered.",
    )
    message: str = Field(description="Human-readable summary, safe to relay verbatim.")


class AppLogTextResult(BaseModel):
    name: str = Field(description="The container the log is from.")
    lines: int = Field(description="How many log lines `text` holds.")
    redactions: int = Field(description="How many secrets or addresses were masked in `text`.")
    truncated: bool = Field(description="True when older lines were left out to fit the size cap.")
    text: str = Field(description="The log lines, newest last, with secrets masked.")
    message: str = Field(description="One-line summary of what `text` holds.")


class AppActionResult(BaseModel):
    name: str = Field(description="The container that was acted on.")
    action: str = Field(description="Which action ran: start, stop, or restart.")
    status: str = Field(description="The container's Docker status after the action ran.")
    message: str = Field(description="Human-readable confirmation, safe to relay verbatim.")
