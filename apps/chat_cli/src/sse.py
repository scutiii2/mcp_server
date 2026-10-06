"""Server-Sent Events, as ember_api writes them: `id:` and `data:` lines, each
event ended by a blank line, `: ping` lines as keep-alives."""

from __future__ import annotations

import json
from typing import Any


def _data_of(line: str) -> str:
    """The value of a `data:` line: what follows the colon, less one space."""
    value = line[5:]
    return value[1:] if value.startswith(" ") else value


class SseParser:
    """Feed it text as it arrives; it returns the events that are complete.
    A partial event waits for the next chunk. An event that is not JSON raises
    ValueError (the caller treats that as a broken stream)."""

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, text: str) -> list[dict[str, Any]]:
        self._buffer += text.replace("\r\n", "\n")
        events: list[dict[str, Any]] = []
        while (boundary := self._buffer.find("\n\n")) != -1:
            block, self._buffer = self._buffer[:boundary], self._buffer[boundary + 2 :]
            data = "\n".join(_data_of(line) for line in block.split("\n") if line.startswith("data:"))
            if not data:
                continue  # a keep-alive
            event = json.loads(data)
            if not isinstance(event, dict):
                raise ValueError("event is not an object")
            events.append(event)
        return events
