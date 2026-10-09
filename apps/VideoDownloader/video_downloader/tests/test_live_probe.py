"""Opt-in check against a real site: `python -m pytest -m live`. Skipped by default (needs internet)."""

from __future__ import annotations

import pytest

from src.extractor.ytdlp import YtDlpExtractor
from src.policy.url_policy import UrlPolicy

pytestmark = pytest.mark.live

VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # "Me at the zoo", the first YouTube upload


async def test_probe_real_youtube_video():
    url = await UrlPolicy().check(VIDEO)
    info = YtDlpExtractor().probe(url)  # default guard: public addresses, ports 80/443 only
    assert info.title
    assert not info.is_live
