"""ember_api's client for apps/mini_games (the Emberlings game).

Only the fixed routes in _ROUTES are reachable; the browser never names a URL.
Every call carries the owner (the account id as text, never the username: an
administrator can rename an account, and its Sparks must not stay behind with
the old name), the internal token when one is configured, and the
Idempotency-Key of a change. Headers are built here only, so nothing the
browser sent is ever forwarded.

mini_games' own refusals (400, 404, 409) keep their status and message, which
is safe to show; any other 4xx becomes a 400. A token mismatch (401), a server
error, a body that is not JSON or no answer at all make Emberlings
"unavailable" (the routes answer 502)."""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

import httpx

from src.models import Account
from src.services.traffic import TrafficRecorder

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0
UNAVAILABLE_MESSAGE = "Emberlings is not available right now"
_PASSED_THROUGH = (400, 404, 409)
# mini_games' ids: server-made tokens and catalog ids.
_ID = r"[A-Za-z0-9_-]{1,64}"
_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (method, re.compile(pattern))
    for method, pattern in (
        ("GET", r"/sparks/catalog"),
        ("GET", r"/sparks/profile"),
        ("POST", r"/sparks/profile"),
        ("GET", rf"/sparks/sparks/{_ID}/personalities"),
        ("GET", rf"/sparks/sparks/{_ID}/presets/[1-5]"),
        ("PUT", rf"/sparks/sparks/{_ID}/presets/[1-5]"),
        ("POST", r"/sparks/encounters"),
        ("GET", rf"/sparks/encounters/{_ID}"),
        ("POST", rf"/sparks/encounters/{_ID}/decline"),
        ("POST", r"/sparks/battles"),
        ("GET", rf"/sparks/battles/{_ID}"),
        ("POST", rf"/sparks/battles/{_ID}/(?:actions|emblem|advance|mode|forfeit)"),
        ("POST", r"/sparks/shop/purchases"),
        ("POST", rf"/sparks/sparks/{_ID}/sales"),
    )
)
# Path words kept in traffic counter names; everything else (ids, slots) becomes {id}.
_WORDS = frozenset(
    "sparks catalog profile personalities presets encounters decline battles actions emblem advance mode "
    "forfeit shop purchases sales".split()
)


class EmberlingsUnavailable(Exception):
    """mini_games could not be used (maps to 502)."""


class EmberlingsRefused(Exception):
    """mini_games refused the request; the message is its own and safe to show."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class EmberlingsApi(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        account: Account,
        *,
        json: Any = None,
        params: dict[str, int | str] | None = None,
        idempotency_key: str | None = None,
    ) -> Any: ...


def is_allowed(method: str, path: str) -> bool:
    return any(method == allowed and pattern.fullmatch(path) for allowed, pattern in _ROUTES)


def _message(body: Any, status: int) -> str:
    if isinstance(body, dict):
        for field in ("error", "detail"):
            value = body.get(field)
            if isinstance(value, str) and value:
                return value
    return f"Emberlings answered {status}"


def _traffic_name(method: str, path: str) -> str:
    """"POST /sparks/battles/abc/advance" -> "POST /sparks/battles/{id}/advance"."""
    return f"{method} /" + "/".join(part if part in _WORDS else "{id}" for part in path.strip("/").split("/"))


class EmberlingsGateway:
    def __init__(
        self, client: httpx.AsyncClient, base_url: str, internal_token: str | None, traffic: TrafficRecorder | None = None
    ) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._internal_token = internal_token
        self._traffic = traffic or TrafficRecorder()

    def _headers(self, account: Account, idempotency_key: str | None) -> dict[str, str]:
        headers = {"X-Requester-Username": str(account.id)}
        if self._internal_token:
            headers["X-Internal-Token"] = self._internal_token
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def request(
        self,
        method: str,
        path: str,
        account: Account,
        *,
        json: Any = None,
        params: dict[str, int | str] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        if not is_allowed(method, path):
            raise ValueError(f"not an Emberlings route: {method} {path}")
        try:
            with self._traffic.timed("mini_games", _traffic_name(method, path)) as timing:
                response = await self._client.request(
                    method,
                    f"{self._base}{path}",
                    json=json,
                    params=params,
                    headers=self._headers(account, idempotency_key),
                    timeout=TIMEOUT_SECONDS,
                )
                timing.ok = response.status_code < 500
        except httpx.HTTPError as error:
            logger.warning("mini_games %s %s unreachable: %s", method, path, error)
            raise EmberlingsUnavailable(str(error)) from error
        status = response.status_code
        if status == 204:
            return None
        try:
            body = response.json()
        except ValueError:
            body = None
        if status == 401:
            logger.warning(
                "mini_games refused ember_api's internal token: INTERNAL_API_TOKEN differs between the two .env files"
            )
            raise EmberlingsUnavailable("mini_games refused the internal token")
        if status in _PASSED_THROUGH:
            raise EmberlingsRefused(status, _message(body, status))
        if 400 <= status < 500:
            raise EmberlingsRefused(400, _message(body, status))
        if status >= 500 or body is None:
            raise EmberlingsUnavailable(f"mini_games answered {status}")
        return body
