from __future__ import annotations

from src import run


def test_main_passes_graceful_shutdown_timeout(monkeypatch, settings):
    calls: list[dict] = []
    monkeypatch.setattr(run, "require_ffmpeg", lambda: None)
    monkeypatch.setattr(run, "load_settings", lambda: settings)
    monkeypatch.setattr(run, "configure_logging", lambda log_dir: None)
    monkeypatch.setattr(run, "create_app", lambda s: "app")
    monkeypatch.setattr(run.uvicorn, "run", lambda app, **kwargs: calls.append({"app": app, **kwargs}))

    run.main()

    assert calls == [
        {"app": "app", "host": settings.host, "port": settings.port, "timeout_graceful_shutdown": run.GRACEFUL_SHUTDOWN_SECONDS}
    ]
