"""llm_config.tiers(): reads a gateway block's optional `models` map."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.llm import llm_config


def _use(monkeypatch, block):
    monkeypatch.setattr(llm_config, "_config", {"anthropic": {"claude": block}})


def test_tiers_are_returned_in_ladder_order_with_trimmed_use_for(monkeypatch):
    _use(monkeypatch, {"models": {
        "heavy": {"id": "opus", "use_for": "hard"},
        "light": {"id": "haiku", "use_for": "  quick  "},
    }})

    found = llm_config.tiers("anthropic", "claude")

    assert list(found) == ["light", "heavy"]
    assert found["light"] == llm_config.TierModel("haiku", "quick")


def test_no_models_means_no_tiers(monkeypatch):
    _use(monkeypatch, {"model": "sonnet"})
    assert llm_config.tiers("anthropic", "claude") == {}


def test_a_placeholder_id_is_resolved_from_the_environment(monkeypatch):
    monkeypatch.setenv("TIER_TEST_MODEL", "my-deployment")
    _use(monkeypatch, {"models": {"standard": {"id": "{TIER_TEST_MODEL}", "use_for": "most"}}})
    assert llm_config.tiers("anthropic", "claude")["standard"].id == "my-deployment"


def test_a_tier_whose_placeholder_is_unset_is_dropped(monkeypatch):
    monkeypatch.delenv("TIER_TEST_MODEL", raising=False)
    _use(monkeypatch, {"models": {
        "light": {"id": "{TIER_TEST_MODEL}", "use_for": "quick"},
        "heavy": {"id": "opus", "use_for": "hard"},
    }})
    assert list(llm_config.tiers("anthropic", "claude")) == ["heavy"]


def test_an_unknown_tier_name_is_rejected(monkeypatch):
    _use(monkeypatch, {"models": {"giant": {"id": "x", "use_for": "y"}}})
    with pytest.raises(ValueError, match="anthropic.claude.models.giant is not a tier"):
        llm_config.tiers("anthropic", "claude")


def test_a_tier_without_use_for_is_rejected(monkeypatch):
    _use(monkeypatch, {"models": {"light": {"id": "x"}}})
    with pytest.raises(ValueError, match="light.use_for must be a non-empty string"):
        llm_config.tiers("anthropic", "claude")


def test_a_tier_without_id_is_rejected(monkeypatch):
    _use(monkeypatch, {"models": {"light": {"use_for": "y"}}})
    with pytest.raises(ValueError, match="light.id must be a non-empty string"):
        llm_config.tiers("anthropic", "claude")


def test_models_must_be_an_object(monkeypatch):
    _use(monkeypatch, {"models": ["light"]})
    with pytest.raises(ValueError, match="models must be an object"):
        llm_config.tiers("anthropic", "claude")


def test_an_unknown_gateway_raises_key_error(monkeypatch):
    _use(monkeypatch, {})
    with pytest.raises(KeyError):
        llm_config.tiers("anthropic", "nope")


@pytest.fixture
def gateway_files(monkeypatch, tmp_path):
    directory = tmp_path / "gateways"
    legacy = tmp_path / "configs" / "config_gateways.json"
    monkeypatch.setattr(llm_config, "GATEWAYS_DIR", directory, raising=False)
    monkeypatch.setattr(llm_config, "_LEGACY_PATH", legacy, raising=False)
    monkeypatch.setattr(llm_config, "_config", None)
    return directory, legacy


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_individual_gateway_files_keep_provider_scopes_and_resolve_env(gateway_files, monkeypatch):
    directory, _ = gateway_files
    _write(directory / "anthropic" / "shared.json", {"model": "claude", "api_key": "{GATEWAY_TEST_KEY}"})
    _write(directory / "openai" / "shared.json", {"model": "gpt"})
    monkeypatch.setenv("GATEWAY_TEST_KEY", "test-key")
    assert llm_config.gateway("anthropic", "shared") == {"model": "claude", "api_key": "test-key"}
    assert llm_config.gateway("openai", "shared") == {"model": "gpt"}


def test_tracked_files_load_without_seeding_examples(gateway_files):
    directory, _ = gateway_files
    _write(directory / "anthropic" / "claude.json", {"model": "custom"})
    _write(directory / "openai" / "gpt.json.example", {"model": "obsolete"})
    assert llm_config.gateway("anthropic", "claude")["model"] == "custom"
    with pytest.raises(KeyError):
        llm_config.gateway("openai", "gpt")
    assert not (directory / "openai" / "gpt.json").exists()


def test_legacy_migration_preserves_custom_settings_and_backup(gateway_files):
    directory, legacy = gateway_files
    old = {"anthropic": {"custom": {"model": "private", "api_key": "{CUSTOM_KEY}"}, "claude": {"model": "old"}}}
    _write(legacy, old)
    _write(directory / "anthropic" / "claude.json", {"model": "new"})
    _write(directory / "openai" / "gpt.json.example", {"model": "default"})
    assert llm_config.gateway("anthropic", "custom")["model"] == "private"
    assert llm_config.gateway("anthropic", "claude")["model"] == "new"
    assert json.loads((directory / "anthropic" / "custom.json").read_text()) == old["anthropic"]["custom"]
    assert json.loads(legacy.read_text()) == old
    # Existing installations keep their configured gateway set, not all example gateways.
    with pytest.raises(KeyError):
        llm_config.gateway("openai", "gpt")


def test_migration_does_not_resurrect_deleted_gateways_or_reread_legacy(gateway_files, monkeypatch):
    directory, legacy = gateway_files
    _write(legacy, {"anthropic": {"claude": {"model": "old"}, "removed": {"model": "old"}}})
    llm_config.gateway("anthropic", "claude")
    (directory / "anthropic" / "removed.json").unlink()
    legacy.write_text("invalid backup", encoding="utf-8")
    monkeypatch.setattr(llm_config, "_config", None)
    assert llm_config.gateway("anthropic", "claude")["model"] == "old"
    with pytest.raises(KeyError):
        llm_config.gateway("anthropic", "removed")


@pytest.mark.parametrize("raw", ["{", '[]', '{"anthropic": []}', '{"anthropic": {"claude": []}}', '{"../escape": {"claude": {}}}'])
def test_invalid_legacy_stops_migration_without_publishing_files(gateway_files, raw):
    directory, legacy = gateway_files
    legacy.parent.mkdir(parents=True)
    legacy.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        llm_config.gateway("anthropic", "claude")
    assert not list(directory.glob("*/*.json"))


def test_invalid_gateway_file_reports_its_path(gateway_files):
    directory, _ = gateway_files
    path = directory / "anthropic" / "claude.json"
    _write(path, [])
    with pytest.raises(ValueError, match="claude.json"):
        llm_config.gateway("anthropic", "claude")


def test_admin_catalog_uses_gateway_files_and_excludes_credentials(gateway_files):
    from src.agents import agent_store

    directory, _ = gateway_files
    _write(directory / "anthropic" / "custom.json", {
        "label": "Custom", "model": "my-model", "api_key": "{CUSTOM_KEY}",
        "models": {"light": {"id": "small", "use_for": "quick tasks"}},
    })
    catalog = agent_store.gateway_catalog()
    assert catalog["anthropic"] == [{"id": "custom", "label": "Custom", "model": "my-model", "tiers": [{"tier": "light", "id": "small"}]}]
    assert catalog["laya"][0]["id"] == "local"
    assert "api_key" not in json.dumps(catalog)


def test_parallel_starts_publish_complete_files(gateway_files):
    directory, legacy = gateway_files
    _write(legacy, {"anthropic": {"claude": {"model": "custom"}}})
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: llm_config.gateway("anthropic", "claude"), range(16)))
    assert results == [{"model": "custom"}] * 16
    assert json.loads((directory / "anthropic" / "claude.json").read_text()) == {"model": "custom"}
    assert not list(directory.glob("**/*.tmp"))


def test_interrupted_migration_retries_without_overwriting_completed_files(gateway_files, monkeypatch):
    directory, legacy = gateway_files
    _write(legacy, {"anthropic": {"claude": {"model": "old"}, "custom": {"model": "second"}}})
    publish = llm_config._publish_missing

    def interrupt(path, content):
        if path.name == "custom.json":
            raise OSError("interrupted")
        publish(path, content)

    monkeypatch.setattr(llm_config, "_publish_missing", interrupt)
    with pytest.raises(OSError, match="interrupted"):
        llm_config.gateway("anthropic", "claude")
    _write(directory / "anthropic" / "claude.json", {"model": "edited"})
    monkeypatch.setattr(llm_config, "_publish_missing", publish)
    assert llm_config.gateway("anthropic", "claude")["model"] == "edited"
    assert llm_config.gateway("anthropic", "custom")["model"] == "second"
