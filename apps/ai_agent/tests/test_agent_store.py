"""agent_store.py: validated create/update/delete of agents/<id>.json."""

from __future__ import annotations

import json

import pytest

from src.agents import agent_store
from src.agents.agent_store import AgentStoreError


def _cfg(port, **extra):
    return {"label": "X", "port": port, "llm": {"provider": "anthropic", "gateway": "claude"}, **extra}


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "ember.json").write_text(json.dumps(_cfg(9100, entry=True)), encoding="utf-8")
    return tmp_path


def test_create_writes_file_and_lists_it(folder):
    agent_store.create_agent("calc", _cfg(9103), folder)
    assert json.loads((folder / "calc.json").read_text())["port"] == 9103
    assert [row["id"] for row in agent_store.list_agents(folder)] == ["calc", "ember"]
    assert not list(folder.glob("*.tmp"))


def test_create_refuses_duplicate_bad_id_port_clash_and_unknown_gateway(folder):
    with pytest.raises(AgentStoreError) as dup:
        agent_store.create_agent("ember", _cfg(9101), folder)
    assert dup.value.status == 409
    with pytest.raises(AgentStoreError):
        agent_store.create_agent("Bad Id", _cfg(9101), folder)
    with pytest.raises(AgentStoreError, match="port 9100"):
        agent_store.create_agent("calc", _cfg(9100), folder)
    with pytest.raises(AgentStoreError, match="gateway"):
        agent_store.create_agent("calc", {"port": 9103, "llm": {"provider": "anthropic", "gateway": "nope"}}, folder)
    with pytest.raises(AgentStoreError, match="llm.provider"):
        agent_store.create_agent("calc", {"port": 9103, "llm": {"provider": "x"}}, folder)
    assert not (folder / "calc.json").exists()


def test_second_entry_agent_is_refused(folder):
    with pytest.raises(AgentStoreError, match="already the entry"):
        agent_store.create_agent("calc", _cfg(9103, entry=True), folder)


def test_update_replaces_file_and_keeps_own_port(folder):
    agent_store.create_agent("calc", _cfg(9103), folder)
    agent_store.update_agent("calc", _cfg(9103, persona="hi"), folder)
    assert agent_store.get_agent("calc", folder)["persona"] == "hi"
    with pytest.raises(AgentStoreError) as missing:
        agent_store.update_agent("ghost", _cfg(9150), folder)
    assert missing.value.status == 404


def test_cannot_unset_the_only_entry_agent(folder):
    with pytest.raises(AgentStoreError, match="entry"):
        agent_store.update_agent("ember", _cfg(9100, entry=False), folder)


def test_delete_removes_file_but_not_the_entry_agent(folder):
    agent_store.create_agent("calc", _cfg(9103), folder)
    agent_store.delete_agent("calc", folder)
    assert not (folder / "calc.json").exists()
    with pytest.raises(AgentStoreError, match="entry agent"):
        agent_store.delete_agent("ember", folder)
    with pytest.raises(AgentStoreError) as missing:
        agent_store.delete_agent("calc", folder)
    assert missing.value.status == 404


def test_gateway_catalog_lists_providers_and_local_laya():
    catalog = agent_store.gateway_catalog()
    assert {"anthropic", "openai", "laya"} <= set(catalog)
    assert any(g["id"] == "openrouter" for g in catalog["anthropic"])
    assert catalog["laya"][0]["id"] == "local"
    assert "api_key" not in json.dumps(catalog)
