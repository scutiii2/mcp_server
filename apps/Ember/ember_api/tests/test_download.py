"""GET /api/server/download: a file a tool offered with a [[DOWNLOAD ...]]
marker, streamed from mcp_server's /download."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeEmailSender, FakeUpstream
from tests.test_admin import login, make_member
from tests.test_registration import as_admin

FILE = b"id,name\n1,Ada\n"
PATH = "/srv/exports/report 1.csv"


def mcp_server(request: httpx.Request) -> httpx.Response:
    if request.url.path != "/download":
        return httpx.Response(404, json={"error": "no route"})
    path = request.url.params.get("path")
    if path == PATH:
        # What a careless server might send: a page type, shown inline.
        return httpx.Response(
            200,
            content=FILE,
            headers={"Content-Type": "text/html", "Content-Disposition": "inline", "Content-Length": str(len(FILE))},
        )
    if path == "/srv/secret":
        return httpx.Response(403, json={"error": "not yours"})
    if path == "/srv/broken":
        return httpx.Response(500, json={"error": "boom"})
    return httpx.Response(404, json={"error": "No such file"})


@pytest.fixture
def served(upstream: FakeUpstream) -> FakeUpstream:
    upstream.handler = mcp_server
    return upstream


def test_a_file_is_streamed_as_an_attachment(client: TestClient, served: FakeUpstream) -> None:
    as_admin(client)

    response = client.get("/api/server/download", params={"path": PATH})

    assert response.status_code == 200, response.text
    assert response.content == FILE
    assert response.headers["content-length"] == str(len(FILE))
    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''report%201.csv"
    assert response.headers["cache-control"] == "no-store"


def test_the_type_is_never_the_one_mcp_server_claims(client: TestClient, served: FakeUpstream) -> None:
    as_admin(client)

    response = client.get("/api/server/download", params={"path": PATH})

    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_the_path_goes_as_a_query_value_with_the_identity(client_factory, upstream: FakeUpstream) -> None:
    upstream.handler = mcp_server
    client = client_factory(internal_token="s3cret")
    as_admin(client)

    client.get("/api/server/download", params={"path": PATH})

    sent = upstream.requests[-1]
    assert sent.method == "GET" and sent.url.path == "/download"
    assert sent.url.params["path"] == PATH
    assert sent.headers["x-requester-username"] == "root"
    assert len(sent.headers["x-requester-uid"]) == 32
    assert sent.headers["x-internal-token"] == "s3cret"


def test_a_path_cannot_add_query_parameters_or_change_the_route(client: TestClient, served: FakeUpstream) -> None:
    as_admin(client)

    client.get("/api/server/download", params={"path": "/x?path=/etc/passwd&y=1"})

    sent = served.requests[-1]
    assert sent.url.path == "/download"
    assert dict(sent.url.params) == {"path": "/x?path=/etc/passwd&y=1"}


def test_a_compressed_body_gets_no_length_that_would_be_wrong_once_decoded(client: TestClient, upstream: FakeUpstream) -> None:
    import gzip

    packed = gzip.compress(FILE)
    upstream.handler = lambda request: httpx.Response(
        200, content=packed, headers={"Content-Encoding": "gzip", "Content-Length": str(len(packed))}
    )
    as_admin(client)

    response = client.get("/api/server/download", params={"path": PATH})

    assert response.content == FILE
    assert response.headers.get("content-length") != str(len(packed))


class TrackedStream(httpx.AsyncByteStream):
    """An upstream body that says whether it was closed."""

    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self):
        yield b"data"

    async def aclose(self) -> None:
        self.closed = True


def test_the_upstream_connection_is_closed_after_the_file_is_sent(client: TestClient, upstream: FakeUpstream) -> None:
    body = TrackedStream()
    upstream.handler = lambda request: httpx.Response(200, stream=body)
    as_admin(client)

    assert client.get("/api/server/download", params={"path": PATH}).content == b"data"

    assert body.closed


@pytest.mark.parametrize("code", [403, 404, 500])
def test_the_upstream_connection_is_closed_when_it_refuses(client: TestClient, upstream: FakeUpstream, code: int) -> None:
    body = TrackedStream()
    upstream.handler = lambda request: httpx.Response(code, stream=body)
    as_admin(client)

    assert client.get("/api/server/download", params={"path": PATH}).status_code != 200

    assert body.closed


def test_a_windows_path_names_the_file_by_its_last_part(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = lambda request: httpx.Response(200, content=b"x")
    as_admin(client)

    response = client.get("/api/server/download", params={"path": r"C:\data\out\sheet.xlsx"})

    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''sheet.xlsx"


def test_a_trailing_slash_or_bare_root_still_gets_a_name(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = lambda request: httpx.Response(200, content=b"x")
    as_admin(client)

    assert client.get("/api/server/download", params={"path": "/data/folder/"}).headers[
        "content-disposition"
    ] == "attachment; filename*=UTF-8''folder"
    assert client.get("/api/server/download", params={"path": "/"}).headers[
        "content-disposition"
    ] == "attachment; filename*=UTF-8''download"


def test_a_name_is_percent_encoded_so_it_cannot_break_the_header(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = lambda request: httpx.Response(200, content=b"x")
    as_admin(client)

    response = client.get("/api/server/download", params={"path": '/a/b"; x=1\u00e9.txt'})

    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''b%22%3B%20x%3D1%C3%A9.txt"


def test_a_missing_file_is_a_404(client: TestClient, served: FakeUpstream) -> None:
    as_admin(client)

    assert client.get("/api/server/download", params={"path": "/nope"}).status_code == 404


def test_a_refusal_is_a_400_without_mcp_servers_message(client: TestClient, served: FakeUpstream) -> None:
    as_admin(client)

    response = client.get("/api/server/download", params={"path": "/srv/secret"})

    assert response.status_code == 400
    assert "not yours" not in response.text


def test_a_broken_or_unreachable_mcp_server_is_a_502(client: TestClient, served: FakeUpstream) -> None:
    as_admin(client)

    assert client.get("/api/server/download", params={"path": "/srv/broken"}).status_code == 502
    served.unreachable = True
    assert client.get("/api/server/download", params={"path": PATH}).status_code == 502


@pytest.mark.parametrize("path", ["", "a\nb", "a\x00b", "a\x7fb", "x" * 1001])
def test_a_bad_path_is_refused_before_anything_is_sent(client: TestClient, served: FakeUpstream, path: str) -> None:
    as_admin(client)
    before = len(served.requests)

    assert client.get("/api/server/download", params={"path": path}).status_code == 422
    assert len(served.requests) == before


def test_a_path_of_the_longest_size_goes_through(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = lambda request: httpx.Response(200, content=b"x")
    as_admin(client)

    assert client.get("/api/server/download", params={"path": "/" + "x" * 999}).status_code == 200


def test_the_path_is_required(client: TestClient, served: FakeUpstream) -> None:
    as_admin(client)

    assert client.get("/api/server/download").status_code == 422


def test_it_needs_a_login_and_a_verified_member_with_tools_use(
    client_factory, email: FakeEmailSender, served: FakeUpstream
) -> None:
    admin = client_factory()
    assert admin.get("/api/server/download", params={"path": PATH}).status_code == 401
    as_admin(admin)

    unverified = client_factory()
    make_member(unverified, email, "kim", verify=False)
    login(unverified, "kim")
    assert unverified.get("/api/server/download", params={"path": PATH}).status_code == 403
    assert len(served.requests) == 0

    member = client_factory()
    make_member(member, email, "alice")
    login(member, "alice")
    assert member.get("/api/server/download", params={"path": PATH}).status_code == 200


# --- the file's name comes from mcp_server -----------------------------------------------------

OPAQUE_ID = "k3J9x_Qm2vA8wLzP5nR7tg"


def disposition(value: str):
    return lambda request: httpx.Response(200, content=b"x", headers={"Content-Disposition": value})


def test_the_name_mcp_server_gives_is_used_not_the_opaque_id(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = disposition("attachment; filename*=UTF-8''web-logs.log")
    as_admin(client)

    response = client.get("/api/server/download", params={"path": OPAQUE_ID})

    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''web-logs.log"


def test_a_percent_encoded_name_from_mcp_server_is_decoded_and_encoded_again(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = disposition("attachment; filename*=UTF-8''report%201%C3%A9.csv")
    as_admin(client)

    response = client.get("/api/server/download", params={"path": OPAQUE_ID})

    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''report%201%C3%A9.csv"


@pytest.mark.parametrize(
    "given, expected",
    [
        ("..%2F..%2Fetc%2Fpasswd", "passwd"),
        ("C%3A%5Cdata%5Cx.log", "x.log"),
        ("a%0D%0ASet-Cookie%3A%20x%3D1.log", "aSet-Cookie%3A%20x%3D1.log"),
    ],
)
def test_a_hostile_name_from_mcp_server_is_cleaned_to_a_bare_name(
    client: TestClient, upstream: FakeUpstream, given: str, expected: str
) -> None:
    upstream.handler = disposition(f"attachment; filename*=UTF-8''{given}")
    as_admin(client)

    response = client.get("/api/server/download", params={"path": OPAQUE_ID})

    assert response.headers["content-disposition"] == f"attachment; filename*=UTF-8''{expected}"


@pytest.mark.parametrize("given", ["..", ".", "%2F", ""])
def test_a_useless_name_from_mcp_server_falls_back_to_the_path(client: TestClient, upstream: FakeUpstream, given: str) -> None:
    upstream.handler = disposition(f"attachment; filename*=UTF-8''{given}")
    as_admin(client)

    response = client.get("/api/server/download", params={"path": "/srv/out/fallback.txt"})

    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''fallback.txt"


def test_a_very_long_name_is_cut(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = disposition(f"attachment; filename*=UTF-8''{'a' * 400}.log")
    as_admin(client)

    response = client.get("/api/server/download", params={"path": OPAQUE_ID})

    assert response.headers["content-disposition"] == f"attachment; filename*=UTF-8''{'a' * 150}"
