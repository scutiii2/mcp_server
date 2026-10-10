"""ember_api's client for apps/mini_games (the Ascension game).

Only the fixed routes in _ROUTES are reachable; the browser never names a URL.
Every call carries the owner (the account id as text, never the username: an
administrator can rename an account, and its Ascended must not stay behind with
the old name), the internal token when one is configured, and the
Idempotency-Key of a change. Headers are built here only, so nothing the
browser sent is ever forwarded.

mini_games' own refusals (400, 404, 409) keep their status and message, which
is safe to show; any other 4xx becomes a 400. A token mismatch (401), a server
error, a body that is not JSON or no answer at all make Ascension
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
UNAVAILABLE_MESSAGE = "Ascension is not available right now"
_PASSED_THROUGH = (400, 404, 409)
MESSAGE_MAX = 300
# mini_games' ids: server-made tokens and catalog ids.
_ID = r"[A-Za-z0-9_-]{1,64}"
_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (method, re.compile(pattern))
    for method, pattern in (
        ("GET", r"/ascension/catalog"),
        ("GET", r"/ascension/profile"),
        ("POST", r"/ascension/profile"),
        ("POST", r"/ascension/profile/reset"),
        ("GET", rf"/ascension/ascendeds/{_ID}/personalities"),
        ("GET", rf"/ascension/ascendeds/{_ID}/presets/[1-5]"),
        ("PUT", rf"/ascension/ascendeds/{_ID}/presets/[1-5]"),
        ("POST", r"/ascension/encounters"),
        ("GET", rf"/ascension/encounters/{_ID}"),
        ("POST", rf"/ascension/encounters/{_ID}/decline"),
        ("POST", r"/ascension/battles"),
        ("GET", rf"/ascension/battles/{_ID}"),
        ("POST", rf"/ascension/battles/{_ID}/(?:actions|emblem|advance|mode|forfeit)"),
        ("POST", r"/ascension/shop/purchases"),
        ("POST", rf"/ascension/ascendeds/{_ID}/sales"),
    )
)
# Path words kept in traffic counter names; everything else (ids, slots) becomes {id}.
_WORDS = frozenset(
    "ascendeds catalog profile personalities presets encounters decline battles actions emblem advance mode "
    "forfeit shop purchases sales reset".split()
)


class AscensionUnavailable(Exception):
    """mini_games could not be used (maps to 502)."""


class AscensionRefused(Exception):
    """mini_games refused the request; the message is its own and safe to show."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class AscensionApi(Protocol):
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

    async def reset_profile(self, account: Account, idempotency_key: str) -> Any: ...


def is_allowed(method: str, path: str) -> bool:
    return any(method == allowed and pattern.fullmatch(path) for allowed, pattern in _ROUTES)


def _message(body: Any, status: int) -> str:
    if isinstance(body, dict):
        for field in ("error", "detail"):
            value = body.get(field)
            if isinstance(value, str) and value:
                return value[:MESSAGE_MAX]
    return f"Ascension answered {status}"


def _traffic_name(method: str, path: str) -> str:
    """"POST /ascension/battles/abc/advance" -> "POST /ascension/battles/{id}/advance"."""
    return f"{method} /" + "/".join(part if part in _WORDS else "{id}" for part in path.strip("/").split("/"))


class AscensionGateway:
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

    async def reset_profile(self, account: Account, idempotency_key: str) -> Any:
        """Wipe the account's Ascension progress. `confirm` is sent here, never taken from the browser."""
        return await self.request(
            "POST", "/ascension/profile/reset", account, json={"confirm": True}, idempotency_key=idempotency_key
        )

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
            raise ValueError(f"not an Ascension route: {method} {path}")
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
                code = response.status_code
                # A token refusal, a server error and a redirect are failures of the link; a 4xx refusal is the game working.
                timing.ok = 200 <= code < 300 or (400 <= code < 500 and code != 401)
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            # Only the error's class: its text can embed the address.
            logger.warning("mini_games %s %s unreachable: %s", method, path, type(error).__name__)
            raise AscensionUnavailable(UNAVAILABLE_MESSAGE) from error
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
            raise AscensionUnavailable(UNAVAILABLE_MESSAGE)
        if status in _PASSED_THROUGH:
            raise AscensionRefused(status, _message(body, status))
        if 400 <= status < 500:
            raise AscensionRefused(400, _message(body, status))
        if not 200 <= status < 300 or body is None:
            # 5xx, a redirect (never followed) or anything else unexpected.
            logger.warning("mini_games %s %s answered %s", method, path, status)
            raise AscensionUnavailable(UNAVAILABLE_MESSAGE)
        return body
