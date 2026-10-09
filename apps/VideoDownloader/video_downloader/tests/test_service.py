from __future__ import annotations

import asyncio
import threading
from dataclasses import replace

import pytest

from src.config import Limits
from src.errors import DownloaderError, ErrorCode
from src.policy.url_policy import UrlPolicy
from src.service import Caller, build_service
from tests.conftest import public_resolver

WEB = Caller("web:1")
URL = "https://example.com/watch?v=1"


async def run_download(service, caller=WEB, preset="720p"):
    job = await service.start_download(caller, URL, preset)
    return job, await service.wait(job)


async def test_probe_returns_options(service):
    result = await service.probe(URL)
    assert result.title == "Cat video"
    assert [o.id for o in result.options] == ["best", "720p", "480p", "audio-mp3", "audio-m4a"]
    assert not any(o.blocked for o in result.options)


async def test_probe_rejects_private_url(service):
    with pytest.raises(DownloaderError) as error:
        await service.probe("http://127.0.0.1/x")
    assert error.value.code == ErrorCode.BLOCKED_HOST


async def test_download_stores_file_and_reports_done(service, fake_extractor):
    job, final = await run_download(service)

    assert final["type"] == "done"
    assert final["file"]["name"] == "Cat video.mp4"
    assert final["file"]["kind"] == "video"
    assert "/api/files/" in final["file"]["download_url"] and "sig=" in final["file"]["download_url"]
    stored = service.get_file(WEB, final["file_id"])
    assert service.file_path(stored).read_bytes() == fake_extractor.content
    types = [e["type"] for e in job.events]
    assert types[0] == "queued" and "progress" in types and "processing" in types and types[-1] == "done"
    assert fake_extractor.calls == [(URL, "720p")]


async def test_audio_preset_makes_audio_file(service):
    _, final = await run_download(service, preset="audio-mp3")
    assert final["file"]["kind"] == "audio" and final["file"]["name"].endswith(".mp3")
    assert final["file"]["mime"] == "audio/mpeg"


async def test_scratch_dir_is_removed(service, settings):
    await run_download(service)
    work = settings.store_dir / "_work"
    assert not work.exists() or not any(work.iterdir())


async def test_unknown_preset_rejected_before_job(service):
    with pytest.raises(DownloaderError) as error:
        await service.start_download(WEB, URL, "8k")
    assert error.value.code == ErrorCode.INVALID_REQUEST


async def test_preset_not_offered_by_site_is_an_error_event(service, fake_extractor):
    fake_extractor.info = replace(fake_extractor.info, formats=fake_extractor.info.formats[:1] + fake_extractor.info.formats[2:])
    _, final = await run_download(service, preset="720p")  # only 360p exists
    assert final["code"] == "invalid_request"


async def test_too_long_video_is_refused(settings, fake_extractor):
    limits = replace(settings.limits, max_duration_seconds=30)
    service = build_service(replace(settings, limits=limits), extractor=fake_extractor, policy=UrlPolicy(public_resolver))
    _, final = await run_download(service)
    assert final["code"] == "too_long" and fake_extractor.calls == []


async def test_live_stream_is_refused(service, fake_extractor):
    fake_extractor.info = replace(fake_extractor.info, duration=None, live_status="is_live")
    _, final = await run_download(service)
    assert final["code"] == "live_stream" and fake_extractor.calls == []


async def test_probe_blocks_every_option_of_a_live_stream(service, fake_extractor):
    fake_extractor.info = replace(fake_extractor.info, duration=None, live_status="is_upcoming")
    result = await service.probe(URL)
    assert result.options and all(o.blocked and o.code == "live_stream" for o in result.options)


async def test_download_rechecks_duration_cap(service, fake_extractor, settings):
    await run_download(service)
    assert fake_extractor.max_durations == [settings.limits.max_duration_seconds]


async def test_cancel_after_probe_skips_download(service, fake_extractor):
    holder: list = []
    fake_extractor.on_probe = lambda: holder[0].cancel()
    job = await service.start_download(WEB, URL, "720p")
    holder.append(job)
    final = await service.wait(job)
    assert final["code"] == "cancelled" and fake_extractor.calls == []


async def test_too_large_estimate_is_refused(settings, fake_extractor):
    limits = replace(settings.limits, max_file_bytes=1_000_000)
    service = build_service(replace(settings, limits=limits), extractor=fake_extractor, policy=UrlPolicy(public_resolver))
    _, final = await run_download(service)  # 720p estimate is about 12 MB
    assert final["code"] == "too_large" and fake_extractor.calls == []


async def test_session_quota_refused_before_download(settings, fake_extractor):
    limits = replace(settings.limits, max_session_bytes=2_000_000)
    service = build_service(replace(settings, limits=limits), extractor=fake_extractor, policy=UrlPolicy(public_resolver))
    _, final = await run_download(service)
    assert final["code"] == "limit_exceeded" and fake_extractor.calls == []


async def test_extractor_error_becomes_error_event(service, fake_extractor):
    fake_extractor.download_error = DownloaderError(ErrorCode.LOGIN_REQUIRED, "Needs login.")
    _, final = await run_download(service)
    assert final == {"type": "error", "code": "login_required", "message": "Needs login."}


async def test_probe_error_inside_job_is_reported(service, fake_extractor):
    fake_extractor.probe_error = DownloaderError(ErrorCode.UNSUPPORTED_SITE, "No.")
    _, final = await run_download(service)
    assert final["code"] == "unsupported_site"


async def test_cancel_running_download(service, fake_extractor):
    fake_extractor.hold = threading.Event()
    job = await service.start_download(WEB, URL, "720p")
    for _ in range(200):
        if fake_extractor.calls:
            break
        await asyncio.sleep(0.01)
    service.cancel_job(WEB, job.id)
    final = await service.wait(job)
    assert final["code"] == "cancelled"


async def test_job_status_progress_done_and_error(service, fake_extractor):
    job, _ = await run_download(service)
    status = service.job_status(WEB, job.id)
    assert status.state == "done" and status.file is not None and status.file.name == "Cat video.mp4"

    fake_extractor.download_error = DownloaderError(ErrorCode.EXTRACTOR_FAILED, "Broken.")
    job2, _ = await run_download(service)
    status2 = service.job_status(WEB, job2.id)
    assert status2.state == "error" and status2.error.code == "extractor_failed"


async def test_job_status_of_done_job_whose_file_is_gone(service):
    job, final = await run_download(service)
    await service.delete_file(WEB, final["file_id"])
    status = service.job_status(WEB, job.id)
    assert status.state == "done" and status.file is None


async def test_files_are_session_scoped_privileged_sees_any(service):
    _, final = await run_download(service)
    other = Caller("web:2")
    assert service.list_files(other) == []
    with pytest.raises(DownloaderError):
        service.get_file(other, final["file_id"])
    assert service.get_file(Caller("mcp:x", privileged=True), final["file_id"]).file_id == final["file_id"]


async def test_other_session_cannot_see_job(service):
    job, _ = await run_download(service)
    with pytest.raises(DownloaderError) as error:
        service.get_job(Caller("web:2"), job.id)
    assert error.value.code == ErrorCode.JOB_NOT_FOUND


async def test_signed_download_checks_signature(service):
    _, final = await run_download(service)
    url = final["file"]["download_url"]
    query = dict(p.split("=") for p in url.split("?", 1)[1].split("&"))
    assert service.file_for_download(final["file_id"], int(query["exp"]), query["sig"]).file_id == final["file_id"]
    with pytest.raises(DownloaderError) as error:
        service.file_for_download(final["file_id"], int(query["exp"]), "bad")
    assert error.value.code == ErrorCode.FILE_NOT_FOUND


async def test_delete_file(service):
    _, final = await run_download(service)
    await service.delete_file(WEB, final["file_id"])
    assert service.list_files(WEB) == []
