from flask import Flask
from werkzeug.exceptions import Forbidden
import pytest

from src.services.security.cross_site import check_cross_site


@pytest.fixture
def app():
    return Flask(__name__)


def test_get_requests_are_always_allowed(app):
    with app.test_request_context("/", method="GET", headers={"Sec-Fetch-Site": "cross-site"}):
        assert check_cross_site() is None


def test_post_with_same_origin_sec_fetch_site_is_allowed(app):
    with app.test_request_context("/", method="POST", headers={"Sec-Fetch-Site": "same-origin"}):
        assert check_cross_site() is None


def test_post_with_none_sec_fetch_site_is_allowed(app):
    with app.test_request_context("/", method="POST", headers={"Sec-Fetch-Site": "none"}):
        assert check_cross_site() is None


def test_post_with_cross_site_sec_fetch_site_is_rejected(app):
    with app.test_request_context("/", method="POST", headers={"Sec-Fetch-Site": "cross-site"}):
        with pytest.raises(Forbidden):
            check_cross_site()


def test_post_with_no_sec_fetch_site_and_matching_origin_is_allowed(app):
    with app.test_request_context("/", method="POST", base_url="http://localhost", headers={"Origin": "http://localhost"}):
        assert check_cross_site() is None


def test_post_with_no_sec_fetch_site_and_mismatched_origin_is_rejected(app):
    with app.test_request_context("/", method="POST", base_url="http://localhost", headers={"Origin": "http://evil.example"}):
        with pytest.raises(Forbidden):
            check_cross_site()


def test_post_with_neither_header_is_allowed(app):
    """No Sec-Fetch-Site and no Origin: a non-browser client (curl, a
    script) - nothing to check against, so it passes, same as
    MCPArchitecture's own check_cross_site."""
    with app.test_request_context("/", method="POST"):
        assert check_cross_site() is None
