# mcp_server src/ Restructure + Capability Toggles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `mcp_server`'s config/secrets/runtime-state from root-level `config.json`/`.env`/`data/`/`logs/` into a `src/configs/` + `src/secrets/` + `src/data/` + `src/logs/` layout mirroring `chat_app`, give each capability its own README (and its own `data/`/`secrets/` when it owns state), and add a `config_capabilities.json`-driven enable/disable toggle per capability.

**Architecture:** `config.json` splits into four dedicated JSON files under `src/configs/` (each file's top-level content **is** the section it replaces - no wrapper key), each backed by real credential values in `src/secrets/*.env`. `run.py` reads `config_capabilities.json` once at startup and skips a capability's tool-registering import when it's disabled. `otp.db` moves inside `capabilities/otp/data/`; `pending_requests.db` stays general under `src/data/` since no single capability owns it.

**Tech Stack:** Python 3.11+, `mcp` (FastMCP) 1.28.0, `python-dotenv`, `pytest`, stdlib `json`/`sqlite3`.

**Spec:** [mcp_server/docs/superpowers/specs/2026-08-23-capability-restructure-design.md](../specs/2026-08-23-capability-restructure-design.md)

## Global Constraints

- Real secret values currently in `mcp_server/.env` and `mcp_server/config.json` (SMTP password, zima's SSH password, approver emails, host inventory) get migrated into the new files with their real values - this is a live deployment, not a scaffold to fill in later.
- Every new gitignored file (`src/secrets/*.env`, `src/configs/*.json`, `src/data/*.db`, `capabilities/otp/data/*.db`) gets a committed `.example` twin.
- `pending_requests_path` and `otp_path` keep their exact field names and env-var overrides (`PENDING_REQUESTS_PATH`, `OTP_PATH`) on `Settings` - only their *default* values change. Nothing that already reads `settings.pending_requests_path` or `settings.otp_path` needs to change.
- `resolve_section` and `load_config` (the generic JSON-parse-and-`${VAR}`-substitute primitives in `infra/app_config.py`) are unchanged - only the per-concern loaders built on top of them (`load_email_config`, `load_hosts_config`/`load_host_config`, `load_extensions_config`/`load_extension_config`, `save_extension_config`/`delete_extension_config`) change, because each now treats the *entire* file it's given as the section, instead of digging out a named sub-key.
- Run `pytest` from `mcp_server/` after every task; every task must leave the suite green before its commit.

---

## Task 1: Split `infra/app_config.py`'s loaders into one file per concern

**Files:**
- Modify: `mcp_server/src/mcp_server/infra/app_config.py`
- Modify: `mcp_server/tests/test_app_config.py`

**Interfaces:**
- Produces: `load_capabilities_config(config_path: Path) -> dict[str, dict[str, Any]]`, `capability_enabled(config: dict[str, dict[str, Any]], name: str) -> bool` - both used by Task 3 (`run.py`).
- Produces (signatures unchanged, bodies changed): `load_email_config(config_path)`, `load_hosts_config(config_path)`, `load_host_config(config_path, name)`, `load_extensions_config(config_path)`, `load_extension_config(config_path, id_)`, `save_extension_config(config_path, config)`, `delete_extension_config(config_path, extension_id)`.
- Consumes: nothing new - `load_config`, `resolve_section`, `EmailConfig`, `HostConfig`, `ExtensionConfig` are untouched.

This task only touches `infra/app_config.py` and its own test file - no other module calls these loaders differently yet (that's Tasks 2 and 4-5). Tests are updated first so the task is TDD: the new tests describe the one-file-per-concern behavior, fail against today's wrapped-section code, then the implementation makes them pass.

- [ ] **Step 1: Update `test_app_config.py` to the one-file-per-concern shape**

Replace the entire file with the content below. This is a mechanical transform of the existing tests (each `_write(tmp_path, {"email": X})` becomes `_write(tmp_path, X)`, same for `"hosts"`/`"extensions"`) plus these deliberate changes:
- Deleted: `test_an_unset_variable_under_hosts_does_not_break_email`, `test_an_unset_variable_under_email_does_not_break_a_host` (the property - one file's missing secret can't break another - is now true by construction, since hosts/email/extensions are different files; nothing left to regression-test).
- Deleted: `test_missing_email_section_raises`, `test_missing_hosts_section_raises`, `test_missing_extensions_section_returns_empty_rather_than_raising`, `test_missing_extensions_section_makes_any_id_unknown`, `test_save_extension_config_creates_the_extensions_section_if_absent`, `test_delete_extension_config_is_idempotent_when_extensions_section_is_absent` (all tested "section key absent from a shared document," a concept that no longer exists once each concern has its own dedicated file - a missing *file* is `FileNotFoundError`, already covered by `test_missing_file_raises_and_names_the_path`).
- Renamed/repurposed: `test_a_host_error_still_names_the_full_dotted_path` and `test_missing_label_names_the_key` now expect the shorter path (`"desktop.password"`, `"reference.label"`) since there's no `hosts.`/`extensions.` wrapper prefix left to name.
- Renamed/repurposed: `test_extensions_section_must_be_an_object` becomes `test_an_extension_entry_that_is_not_an_object_is_rejected` - the "whole section isn't an object" case is now just `load_config`'s existing top-level-must-be-an-object check (already covered by `test_top_level_array_is_rejected`), so this test now covers the still-distinct "one entry isn't an object" case instead.
- Renamed/repurposed: `test_save_extension_config_preserves_other_sections_and_entries` and `test_delete_extension_config_preserves_other_sections_and_entries` now preserve *other extension entries* in the same file, not other config sections (there are no other sections in this file anymore).
- Added: a `test_empty_hosts_file_means_zero_hosts_configured` test for the new "empty `{}` is a normal zero-hosts state" behavior.
- Added: a `# --- capabilities ---` section testing `load_capabilities_config`/`capability_enabled`.
- Unchanged: every test that calls `load_config`/`resolve_section` directly rather than through a section-specific loader (the `${VAR}`-substitution mechanics tests, `_resolve`, file-handling tests) - these are generic primitive tests, not affected by which loader reads which file.

```python
"""Tests for infra/app_config.py.

The point of this module is that it fails loudly, so most of these assert
on the *error*, not the happy path - a config loader that returns ``{}``
on a missing file is exactly what this project avoids.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_server.infra.app_config import (
    EmailConfig,
    ExtensionConfig,
    capability_enabled,
    delete_extension_config,
    load_capabilities_config,
    load_config,
    load_email_config,
    load_extension_config,
    load_extensions_config,
    load_host_config,
    load_hosts_config,
    resolve_section,
    save_extension_config,
)


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _resolve(path: Path, name: str):
    """Resolve one top-level key the way a caller resolving an arbitrary
    subtree would - unrelated to which loader reads which file; these
    tests exercise ``resolve_section`` itself, not a specific loader."""
    return resolve_section(load_config(path)[name], where=name, config_path=path)


VALID_EMAIL = {
    "smtp_server": "smtp.example.com",
    "smtp_port": 587,
    "from": "notifications@example.com",
    "password": "changeme",
    "to": ["team@example.com"],
}

VALID_HOSTS = {
    "zima": {"hostname": "192.168.1.10", "user": "root", "os": "linux", "key": "/root/.ssh/id"},
    "desktop": {"hostname": "192.168.1.20", "user": "User", "os": "windows", "password": "pw"},
}

VALID_EXTENSIONS = {
    "reference": {
        "label": "Reference Extension",
        "description": "Dev fixture",
        "command": "python",
        "args": ["-m", "mcp_server._fixtures.reference_extension_server"],
    },
    "other": {
        "label": "Other Extension",
        "description": "Another one",
        "command": "python",
        "args": [],
    },
}


# --- ${VAR} resolution -------------------------------------------------
# The point of this feature is that a config file names secrets instead
# of holding them, so these cover both halves: the value arriving
# correctly, and a clear failure when the environment doesn't supply it.
# Exercised through load_email_config, but nothing here is email-specific
# - every loader shares the same resolve_section machinery.


def test_placeholder_is_replaced_with_the_environment_value(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "s3cret")
    path = _write(tmp_path, {**VALID_EMAIL, "password": "${SMTP_PASSWORD}"})

    assert load_email_config(path).password == "s3cret"


def test_placeholder_can_be_embedded_in_a_larger_string(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MAIL_HOST", "mail.internal")
    path = _write(tmp_path, {**VALID_EMAIL, "smtp_server": "smtp.${MAIL_HOST}.example"})

    assert load_email_config(path).smtp_server == "smtp.mail.internal.example"


def test_placeholders_resolve_inside_lists(tmp_path: Path, monkeypatch):
    """Resolution walks the whole structure, so a key added later gets it
    without touching this module."""
    monkeypatch.setenv("ONCALL_EMAIL", "oncall@example.com")
    path = _write(tmp_path, {**VALID_EMAIL, "to": ["team@example.com", "${ONCALL_EMAIL}"]})

    assert load_email_config(path).to == ["team@example.com", "oncall@example.com"]


def test_unset_variable_raises_naming_both_the_variable_and_the_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    path = _write(tmp_path, {**VALID_EMAIL, "password": "${SMTP_PASSWORD}"})

    with pytest.raises(KeyError) as error:
        load_email_config(path)

    message = str(error.value)
    assert "SMTP_PASSWORD" in message
    assert "password" in message  # the JSON key, so you know where to look


def test_empty_variable_raises_rather_than_yielding_a_blank_secret(tmp_path: Path, monkeypatch):
    """An unset var and a blank one are the same mistake in practice
    ("SMTP_PASSWORD=" in .env); failing here beats a confusing SMTP
    login error later."""
    monkeypatch.setenv("SMTP_PASSWORD", "")
    path = _write(tmp_path, {**VALID_EMAIL, "password": "${SMTP_PASSWORD}"})

    with pytest.raises(ValueError, match="empty string"):
        load_email_config(path)


def test_literal_empty_string_is_still_allowed(tmp_path: Path):
    """The documented escape hatch: write "" directly if empty is intended."""
    path = _write(tmp_path, {**VALID_EMAIL, "password": ""})

    assert load_email_config(path).password == ""


def test_non_string_values_pass_through_untouched(tmp_path: Path):
    path = _write(tmp_path, {"email": VALID_EMAIL, "extras": {"count": 3, "on": True, "nothing": None}})

    assert _resolve(path, "extras") == {"count": 3, "on": True, "nothing": None}


def test_bare_dollar_signs_are_not_treated_as_placeholders(tmp_path: Path):
    """Only ${NAME} interpolates - a lone "$" is ordinary text, so shell-ish
    or currency strings survive intact."""
    path = _write(tmp_path, {"email": VALID_EMAIL, "note": "costs US$5, not $HOME"})

    assert _resolve(path, "note") == "costs US$5, not $HOME"


def test_double_dollar_escapes_a_literal_placeholder(tmp_path: Path, monkeypatch):
    """Without an escape there'd be no way to store text that genuinely
    contains ${...} - which is easy to hit by accident (a comment
    describing this very syntax, for instance)."""
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    path = _write(tmp_path, {"email": VALID_EMAIL, "note": "write $${SMTP_PASSWORD} to refer to it"})

    assert _resolve(path, "note") == "write ${SMTP_PASSWORD} to refer to it"


def test_double_dollar_outside_a_placeholder_becomes_one_dollar(tmp_path: Path):
    path = _write(tmp_path, {"email": VALID_EMAIL, "note": "costs 5$$"})

    assert _resolve(path, "note") == "costs 5$"


def test_placeholder_value_is_not_itself_expanded(tmp_path: Path, monkeypatch):
    """No recursive expansion: whatever the environment holds is used
    literally, so a value that happens to contain ${...} can't trigger
    another lookup."""
    monkeypatch.setenv("WEIRD", "${NOT_A_VAR}")
    monkeypatch.delenv("NOT_A_VAR", raising=False)
    path = _write(tmp_path, {"email": VALID_EMAIL, "note": "${WEIRD}"})

    assert _resolve(path, "note") == "${NOT_A_VAR}"


# --- lazy, per-entry resolution -----------------------------------------
# Resolving a whole file up front meant one unset variable anywhere broke
# every unrelated entry in it. These pin the fix down for the cases that
# still share one file: several hosts, or several extensions.


def test_a_broken_host_does_not_break_a_sibling_host(tmp_path: Path, monkeypatch):
    """Resolution is per *entry*, not per file. Loading every host and
    then indexing would read the same and pass every other test here,
    while leaving one unreachable machine able to lock you out of the
    others - which is precisely when you need them."""
    monkeypatch.delenv("DESKTOP_SSH_PASSWORD", raising=False)
    path = _write(
        tmp_path,
        {
            "zima": VALID_HOSTS["zima"],
            "desktop": {**VALID_HOSTS["desktop"], "password": "${DESKTOP_SSH_PASSWORD}"},
        },
    )

    assert load_host_config(path, "zima").key == "/root/.ssh/id"

    # ...and the broken one still fails, loudly, when it is the one asked for.
    with pytest.raises(KeyError, match="DESKTOP_SSH_PASSWORD"):
        load_host_config(path, "desktop")


def test_loading_all_hosts_still_fails_when_any_host_is_broken(tmp_path: Path, monkeypatch):
    """The one caller that legitimately needs every secret: it returns the
    whole inventory, so skipping the entry it couldn't resolve would hand
    back a silently short list and read as 'that host isn't configured'."""
    monkeypatch.delenv("DESKTOP_SSH_PASSWORD", raising=False)
    path = _write(
        tmp_path,
        {
            "zima": VALID_HOSTS["zima"],
            "desktop": {**VALID_HOSTS["desktop"], "password": "${DESKTOP_SSH_PASSWORD}"},
        },
    )

    with pytest.raises(KeyError, match="DESKTOP_SSH_PASSWORD"):
        load_hosts_config(path)


def test_a_host_error_names_the_entry_and_the_key(tmp_path: Path, monkeypatch):
    """The operator's next move is to open config_hosts.json and find the
    line, so the message has to name the entry, not just the bare key -
    'password' alone could be any host's password."""
    monkeypatch.delenv("DESKTOP_SSH_PASSWORD", raising=False)
    path = _write(tmp_path, {"desktop": {**VALID_HOSTS["desktop"], "password": "${DESKTOP_SSH_PASSWORD}"}})

    with pytest.raises(KeyError) as error:
        load_host_config(path, "desktop")

    assert "desktop.password" in str(error.value)


def test_load_config_leaves_placeholders_unresolved(tmp_path: Path, monkeypatch):
    """load_config is parse-and-validate only. If it resolved anything it
    would demand every secret in the file regardless of which loader
    reads it - so the placeholder surviving verbatim is the property."""
    monkeypatch.delenv("DESKTOP_SSH_PASSWORD", raising=False)
    path = _write(tmp_path, {"desktop": {"password": "${DESKTOP_SSH_PASSWORD}"}})

    assert load_config(path)["desktop"]["password"] == "${DESKTOP_SSH_PASSWORD}"


# --- file handling -----------------------------------------------------


def test_load_config_returns_the_parsed_object(tmp_path: Path):
    path = _write(tmp_path, {"email": VALID_EMAIL})
    assert load_config(path) == {"email": VALID_EMAIL}


def test_missing_file_raises_and_names_the_path(tmp_path: Path):
    missing = tmp_path / "nope.json"
    with pytest.raises(FileNotFoundError, match="nope.json"):
        load_config(missing)


def test_invalid_json_raises_rather_than_returning_empty(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_config(path)


def test_top_level_array_is_rejected(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_config(path)


def test_load_email_config_maps_from_to_from_address(tmp_path: Path):
    """``from`` is a Python keyword, so the dataclass field can't share its
    name - this is the one place that rename happens."""
    path = _write(tmp_path, VALID_EMAIL)

    config = load_email_config(path)

    assert config == EmailConfig(
        smtp_server="smtp.example.com",
        smtp_port=587,
        from_address="notifications@example.com",
        password="changeme",
        to=["team@example.com"],
        approver_emails=["team@example.com"],
    )


def test_approver_emails_default_to_the_general_recipients(tmp_path: Path):
    """Splitting the two audiences should be available without being
    mandatory - a config that never gates anything shouldn't have to
    think about it."""
    path = _write(tmp_path, VALID_EMAIL)

    assert load_email_config(path).approver_emails == ["team@example.com"]


def test_approver_emails_override_the_general_recipients(tmp_path: Path):
    """When set, approvers are a *different* list, not an addition to it -
    an approval link is authority to run something irreversible, and
    everyone on the general notification list shouldn't inherit that."""
    path = _write(tmp_path, {**VALID_EMAIL, "approver_emails": ["boss@example.com"]})

    config = load_email_config(path)

    assert config.approver_emails == ["boss@example.com"]
    assert config.to == ["team@example.com"]


def test_missing_required_key_names_the_key(tmp_path: Path):
    incomplete = {k: v for k, v in VALID_EMAIL.items() if k != "smtp_server"}
    path = _write(tmp_path, incomplete)
    with pytest.raises(KeyError, match="smtp_server"):
        load_email_config(path)


def test_to_may_be_omitted_entirely(tmp_path: Path):
    """A deployment that only mails one-time codes to caller-supplied
    addresses has no standing recipient list, and requiring one forces an
    invented address into the config - which then also joins the OTP
    allowlist, quietly widening exactly the thing it feeds."""
    no_to = {k: v for k, v in VALID_EMAIL.items() if k != "to"}
    path = _write(tmp_path, {**no_to, "approver_emails": ["boss@example.com"]})

    config = load_email_config(path)

    assert config.to == []
    assert config.approver_emails == ["boss@example.com"]


def test_to_and_approver_emails_may_both_be_absent(tmp_path: Path):
    """Load time is the wrong place to reject this: send_email raises "No
    recipients" and the OTP capability raises its own KeyError naming the
    keys to add, both at the moment it matters. A load-time failure would
    instead block a config that only ever sends where the caller says."""
    no_to = {k: v for k, v in VALID_EMAIL.items() if k != "to"}
    path = _write(tmp_path, {**no_to, "allowed_recipient_domains": ["example.com"]})

    config = load_email_config(path)

    assert config.to == []
    assert config.approver_emails == []
    assert config.allowed_recipient_domains == ["example.com"]


def test_password_may_be_omitted_entirely(tmp_path: Path):
    """An unauthenticated send is a real configuration - a LAN relay that
    authorizes by source address - not an oversight. Demanding the key
    would force a dummy value that then gets offered to a server with no
    AUTH extension, which fails the send."""
    no_password = {k: v for k, v in VALID_EMAIL.items() if k != "password"}
    path = _write(tmp_path, no_password)

    assert load_email_config(path).password == ""


def test_security_defaults_to_starttls_on_a_submission_port(tmp_path: Path):
    path = _write(tmp_path, VALID_EMAIL)

    assert load_email_config(path).security == "starttls"


def test_port_465_infers_implicit_tls(tmp_path: Path):
    """465 is the registered implicit-TLS submission port and every
    mainstream provider uses it as such, so the port is enough to know the
    transport - saving a field that would otherwise be wrong-by-default
    for the most common consumer setup."""
    path = _write(tmp_path, {**VALID_EMAIL, "smtp_port": 465})

    assert load_email_config(path).security == "ssl"


def test_explicit_security_beats_the_port_inference(tmp_path: Path):
    """Inference is a convenience, not a rule: a relay can listen for
    STARTTLS on 465, and the config file has to win when it disagrees."""
    path = _write(tmp_path, {**VALID_EMAIL, "smtp_port": 465, "security": "starttls"})

    assert load_email_config(path).security == "starttls"


def test_security_is_normalized(tmp_path: Path):
    path = _write(tmp_path, {**VALID_EMAIL, "security": " SSL "})

    assert load_email_config(path).security == "ssl"


def test_unsupported_security_is_rejected_rather_than_falling_back(tmp_path: Path):
    """A typo must not quietly become a plaintext connection: the password
    would go out in the clear and nothing in the run would say so."""
    path = _write(tmp_path, {**VALID_EMAIL, "security": "tls"})

    with pytest.raises(ValueError, match="expected one of"):
        load_email_config(path)


def test_single_recipient_string_is_accepted_as_a_list(tmp_path: Path):
    """A bare string is the obvious thing to write for one recipient, and
    silently iterating it character-by-character would be a nasty way to
    find out otherwise."""
    path = _write(tmp_path, {**VALID_EMAIL, "to": "solo@example.com"})

    assert load_email_config(path).to == ["solo@example.com"]


def test_string_port_is_coerced_to_int(tmp_path: Path):
    path = _write(tmp_path, {**VALID_EMAIL, "smtp_port": "587"})

    assert load_email_config(path).smtp_port == 587


# --- allowed_recipient_domains -----------------------------------------
# The OTP capability sends a passcode to any address at these domains, so
# the loader's job is to produce exactly what the operator wrote - and,
# above all, to produce *nothing* when they wrote nothing.


def test_omitting_allowed_recipient_domains_allows_no_domains(tmp_path: Path):
    """The dangerous default, tested directly. An absent key must mean "no
    domains", never "any domain" - the inverted version still passes every
    happy-path test while turning the OTP tool into an open mail relay."""
    path = _write(tmp_path, VALID_EMAIL)

    assert load_email_config(path).allowed_recipient_domains == []


def test_allowed_recipient_domains_are_loaded_in_order(tmp_path: Path):
    path = _write(tmp_path, {**VALID_EMAIL, "allowed_recipient_domains": ["example.com", "example.org"]})

    assert load_email_config(path).allowed_recipient_domains == ["example.com", "example.org"]


def test_domains_are_normalized_to_bare_lowercase(tmp_path: Path):
    """Asked for a domain, people write "@example.com" or ".example.com"
    as readily as the bare form, and mail domains are case-insensitive
    anyway. A config that looks right and matches nothing is the worst
    outcome available here: it reads as configured."""
    path = _write(
        tmp_path,
        {
            **VALID_EMAIL,
            "allowed_recipient_domains": ["  Example.COM ", "@Corp.example", ".mail.example"],
        },
    )

    assert load_email_config(path).allowed_recipient_domains == [
        "example.com",
        "corp.example",
        "mail.example",
    ]


def test_blank_domain_entries_are_dropped(tmp_path: Path):
    """A leftover "" can only fail to match, so it widens nothing - but it
    would show up in the refusal message a caller reads to work out what
    it should have asked for."""
    path = _write(tmp_path, {**VALID_EMAIL, "allowed_recipient_domains": ["", "  "]})

    assert load_email_config(path).allowed_recipient_domains == []


def test_a_single_domain_string_is_accepted_as_a_list(tmp_path: Path):
    """Same reasoning as 'to': iterating a bare string character by
    character would produce a list of one-letter domains."""
    path = _write(tmp_path, {**VALID_EMAIL, "allowed_recipient_domains": "example.com"})

    assert load_email_config(path).allowed_recipient_domains == ["example.com"]


def test_domains_resolve_placeholders_and_are_still_normalized(tmp_path: Path):
    """${VAR} resolution happens before normalization, so a domain supplied
    by the environment gets the same treatment as one typed into the file
    - otherwise the two ways of configuring the same thing disagree."""
    data = {**VALID_EMAIL, "allowed_recipient_domains": ["${STAFF_DOMAIN}"]}
    path = _write(tmp_path, data)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("STAFF_DOMAIN", "@Staff.Example")

        assert load_email_config(path).allowed_recipient_domains == ["staff.example"]


# --- hosts -------------------------------------------------------------


def test_hosts_are_keyed_by_name(tmp_path: Path):
    path = _write(tmp_path, VALID_HOSTS)

    hosts = load_hosts_config(path)

    assert set(hosts) == {"zima", "desktop"}
    assert hosts["zima"].name == "zima"
    assert hosts["desktop"].os == "windows"


def test_port_defaults_to_22(tmp_path: Path):
    path = _write(tmp_path, VALID_HOSTS)

    assert load_hosts_config(path)["zima"].port == 22


def test_os_is_normalized(tmp_path: Path):
    path = _write(tmp_path, {"a": {**VALID_HOSTS["zima"], "os": "  Linux "}})

    assert load_hosts_config(path)["a"].os == "linux"


def test_unsupported_os_is_rejected(tmp_path: Path):
    """The OS picks the entire command set, so a typo would otherwise
    surface as a pile of 'command not found'."""
    path = _write(tmp_path, {"a": {**VALID_HOSTS["zima"], "os": "darwin"}})

    with pytest.raises(ValueError, match="expected one of"):
        load_hosts_config(path)


def test_host_without_key_or_password_is_rejected(tmp_path: Path):
    """Failing here beats failing at connect time, where it looks like a
    wrong password rather than a missing one."""
    path = _write(tmp_path, {"a": {"hostname": "h", "user": "u", "os": "linux"}})

    with pytest.raises(KeyError, match="needs a 'key' or a 'password'"):
        load_hosts_config(path)


def test_host_secrets_resolve_from_the_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DESKTOP_SSH_PASSWORD", "hunter2")
    path = _write(tmp_path, {"a": {**VALID_HOSTS["desktop"], "password": "${DESKTOP_SSH_PASSWORD}"}})

    assert load_hosts_config(path)["a"].password == "hunter2"


def test_unknown_host_names_the_ones_that_exist(tmp_path: Path):
    """The caller is usually a model that guessed a name; the fix is
    knowing what it could have said."""
    path = _write(tmp_path, VALID_HOSTS)

    with pytest.raises(KeyError, match="desktop, zima"):
        load_host_config(path, "nas")


def test_empty_hosts_file_means_zero_hosts_configured(tmp_path: Path):
    """A fresh config_hosts.json (just "{}") is a normal "nothing
    configured yet" state now that the file *is* the hosts map - not an
    error the way an entirely absent "hosts" key inside a shared document
    used to be."""
    path = _write(tmp_path, {})

    assert load_hosts_config(path) == {}
    with pytest.raises(KeyError, match="none configured"):
        load_host_config(path, "zima")


# --- extensions ----------------------------------------------------------
# Mirrors the "hosts" tests above - same per-entry resolution, same
# broken-sibling isolation.


def test_extensions_are_keyed_by_id(tmp_path: Path):
    path = _write(tmp_path, VALID_EXTENSIONS)

    extensions = load_extensions_config(path)

    assert set(extensions) == {"reference", "other"}
    assert extensions["reference"].id == "reference"
    assert extensions["reference"].command == "python"
    assert extensions["reference"].args == ["-m", "mcp_server._fixtures.reference_extension_server"]


def test_args_default_to_empty_list(tmp_path: Path):
    no_args = {k: v for k, v in VALID_EXTENSIONS["reference"].items() if k != "args"}
    path = _write(tmp_path, {"reference": no_args})

    assert load_extensions_config(path)["reference"].args == []


def test_description_defaults_to_empty_string(tmp_path: Path):
    """Unlike `label` (shown as the extension's name in a UI, so it must
    be spelled out) or `command` (nothing works without it), a missing
    description degrades gracefully - it's cosmetic, not load-bearing."""
    no_description = {k: v for k, v in VALID_EXTENSIONS["reference"].items() if k != "description"}
    path = _write(tmp_path, {"reference": no_description})

    assert load_extensions_config(path)["reference"].description == ""


def test_missing_command_and_url_is_rejected(tmp_path: Path):
    """Before the http transport existed, 'command' was unconditionally
    required and its absence raised KeyError naming the key. Now
    'command' xor 'url' is required - omitting 'command' alone is only an
    error because 'url' isn't present either (see
    test_extension_with_neither_command_nor_url_is_rejected), so this
    raises the mutual-exclusion ValueError rather than a KeyError about
    'command' specifically."""
    no_command = {k: v for k, v in VALID_EXTENSIONS["reference"].items() if k != "command"}
    path = _write(tmp_path, {"reference": no_command})

    with pytest.raises(ValueError, match="'command'.*'url'"):
        load_extensions_config(path)


def test_missing_label_names_the_entry_and_the_key(tmp_path: Path):
    no_label = {k: v for k, v in VALID_EXTENSIONS["reference"].items() if k != "label"}
    path = _write(tmp_path, {"reference": no_label})

    with pytest.raises(KeyError, match="reference.label"):
        load_extensions_config(path)


def test_extension_args_resolve_placeholders(tmp_path: Path, monkeypatch):
    """The documented future use case: a bearer token passed as a CLI
    arg, named rather than written down, same as hosts.<name>.password."""
    monkeypatch.setenv("REFERENCE_TOKEN", "s3cret")
    path = _write(
        tmp_path,
        {"reference": {**VALID_EXTENSIONS["reference"], "args": ["--token", "${REFERENCE_TOKEN}"]}},
    )

    assert load_extensions_config(path)["reference"].args == ["--token", "s3cret"]


def test_a_broken_extension_does_not_break_a_sibling_extension(tmp_path: Path, monkeypatch):
    """Same property as the equivalent host test: resolution is per
    entry, so one extension's unset secret can't take a working sibling
    down with it - which is exactly when you'd still want the working one
    available."""
    monkeypatch.delenv("MISSING_TOKEN", raising=False)
    path = _write(
        tmp_path,
        {
            "reference": VALID_EXTENSIONS["reference"],
            "broken": {**VALID_EXTENSIONS["other"], "args": ["${MISSING_TOKEN}"]},
        },
    )

    assert load_extension_config(path, "reference").command == "python"

    with pytest.raises(KeyError, match="MISSING_TOKEN"):
        load_extension_config(path, "broken")


def test_loading_all_extensions_still_fails_when_any_is_broken(tmp_path: Path, monkeypatch):
    """The one caller that legitimately needs every extension: it returns
    the whole configured set, so skipping the broken one would hand back
    a silently short list."""
    monkeypatch.delenv("MISSING_TOKEN", raising=False)
    path = _write(
        tmp_path,
        {
            "reference": VALID_EXTENSIONS["reference"],
            "broken": {**VALID_EXTENSIONS["other"], "args": ["${MISSING_TOKEN}"]},
        },
    )

    with pytest.raises(KeyError, match="MISSING_TOKEN"):
        load_extensions_config(path)


def test_unknown_extension_names_the_ones_that_exist(tmp_path: Path):
    path = _write(tmp_path, VALID_EXTENSIONS)

    with pytest.raises(KeyError, match="other, reference"):
        load_extension_config(path, "nope")


def test_an_extension_entry_that_is_not_an_object_is_rejected(tmp_path: Path):
    path = _write(tmp_path, {"reference": "not-a-dict"})

    with pytest.raises(ValueError, match="must be an object"):
        load_extensions_config(path)


def test_extension_entry_args_must_be_a_list(tmp_path: Path):
    path = _write(tmp_path, {"reference": {**VALID_EXTENSIONS["reference"], "args": "not-a-list"}})

    with pytest.raises(ValueError, match="must be a list"):
        load_extensions_config(path)


def test_load_extensions_config_returns_extension_config_instances(tmp_path: Path):
    path = _write(tmp_path, {"reference": VALID_EXTENSIONS["reference"]})

    assert load_extensions_config(path)["reference"] == ExtensionConfig(
        id="reference",
        label="Reference Extension",
        description="Dev fixture",
        transport="stdio",
        command="python",
        args=["-m", "mcp_server._fixtures.reference_extension_server"],
    )


# --- extensions: http transport -----------------------------------------
# A second way to reach an extension: connect to a URL instead of spawning
# a subprocess. 'command' and 'url' are mutually exclusive - exactly one
# is required - since together they'd say two different things about how
# to reach the same extension, and neither says it unambiguously alone.


def test_http_extension_entry_parses_correctly(tmp_path: Path):
    path = _write(
        tmp_path,
        {
            "remote": {
                "label": "Remote Extension",
                "description": "An http-transport extension",
                "url": "http://127.0.0.1:9000/mcp",
            }
        },
    )

    config = load_extensions_config(path)["remote"]

    assert config == ExtensionConfig(
        id="remote",
        label="Remote Extension",
        description="An http-transport extension",
        transport="http",
        url="http://127.0.0.1:9000/mcp",
    )


def test_extension_with_both_command_and_url_is_rejected(tmp_path: Path):
    path = _write(
        tmp_path,
        {"confused": {"label": "Confused", "command": "python", "url": "http://127.0.0.1:9000/mcp"}},
    )

    with pytest.raises(ValueError, match="both 'command' and 'url'"):
        load_extensions_config(path)


def test_extension_with_neither_command_nor_url_is_rejected(tmp_path: Path):
    path = _write(tmp_path, {"nothing": {"label": "Nothing"}})

    with pytest.raises(ValueError, match="'command'.*'url'"):
        load_extensions_config(path)


def test_http_extension_url_resolves_placeholders(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("UPSTREAM_HOST", "upstream.internal")
    path = _write(tmp_path, {"remote": {"label": "Remote", "url": "http://${UPSTREAM_HOST}:9000/mcp"}})

    assert load_extensions_config(path)["remote"].url == "http://upstream.internal:9000/mcp"


def test_http_extension_empty_url_is_rejected(tmp_path: Path):
    path = _write(tmp_path, {"remote": {"label": "Remote", "url": "   "}})

    with pytest.raises(ValueError, match="must not be empty"):
        load_extensions_config(path)


# --- save_extension_config / delete_extension_config ----------------------
# The runtime add/remove routes (extension_routes.py) persist through
# these, so a successful HTTP response and config_extensions.json agreeing
# about what extensions exist depends on them round-tripping correctly -
# and, just as important, not disturbing any other entry in the file.


def test_save_extension_config_adds_a_new_http_entry(tmp_path: Path):
    path = _write(tmp_path, {})

    save_extension_config(
        path,
        ExtensionConfig(id="remote", label="Remote", description="desc", transport="http", url="http://x/mcp"),
    )

    data = load_config(path)
    assert data["remote"] == {"label": "Remote", "description": "desc", "url": "http://x/mcp"}


def test_save_extension_config_adds_a_new_stdio_entry(tmp_path: Path):
    path = _write(tmp_path, {})

    save_extension_config(
        path,
        ExtensionConfig(
            id="local", label="Local", description="desc", transport="stdio", command="python", args=["-m", "x"]
        ),
    )

    data = load_config(path)
    assert data["local"] == {"label": "Local", "description": "desc", "command": "python", "args": ["-m", "x"]}


def test_save_extension_config_overwrites_an_existing_entry_by_id(tmp_path: Path):
    path = _write(tmp_path, {"remote": {"label": "Old", "description": "", "url": "http://old/mcp"}})

    save_extension_config(
        path,
        ExtensionConfig(id="remote", label="New", description="", transport="http", url="http://new/mcp"),
    )

    assert load_config(path)["remote"]["url"] == "http://new/mcp"
    assert load_config(path)["remote"]["label"] == "New"


def test_save_extension_config_preserves_other_extension_entries(tmp_path: Path):
    path = _write(tmp_path, {"other": VALID_EXTENSIONS["other"]})

    save_extension_config(
        path, ExtensionConfig(id="remote", label="Remote", description="", transport="http", url="http://x/mcp")
    )

    data = load_config(path)
    assert data["other"] == VALID_EXTENSIONS["other"]
    assert "remote" in data


def test_delete_extension_config_removes_the_entry(tmp_path: Path):
    path = _write(tmp_path, {"remote": {"label": "Remote", "description": "", "url": "http://x/mcp"}})

    delete_extension_config(path, "remote")

    assert "remote" not in load_config(path)


def test_delete_extension_config_preserves_other_extension_entries(tmp_path: Path):
    path = _write(
        tmp_path,
        {
            "remote": {"label": "Remote", "description": "", "url": "http://x/mcp"},
            "other": VALID_EXTENSIONS["other"],
        },
    )

    delete_extension_config(path, "remote")

    data = load_config(path)
    assert "remote" not in data
    assert data["other"] == VALID_EXTENSIONS["other"]


def test_delete_extension_config_is_idempotent_for_an_unknown_id(tmp_path: Path):
    path = _write(tmp_path, {"other": VALID_EXTENSIONS["other"]})

    delete_extension_config(path, "does-not-exist")  # must not raise

    assert set(load_config(path)) == {"other"}


# --- capabilities --------------------------------------------------------
# config_capabilities.json toggles built-in capabilities on/off. Absence -
# of the file, or of a capability's own entry within it - must mean
# enabled, so a fresh or partial toggle file never silently disables
# everything it doesn't mention.


def test_capability_enabled_defaults_to_true_when_file_is_missing(tmp_path: Path):
    missing = tmp_path / "config_capabilities.json"

    assert capability_enabled(load_capabilities_config(missing), "otp") is True


def test_capability_enabled_defaults_to_true_when_entry_is_absent(tmp_path: Path):
    path = _write(tmp_path, {"otp": {"enabled": True}})

    assert capability_enabled(load_capabilities_config(path), "host_health") is True


def test_capability_can_be_explicitly_disabled(tmp_path: Path):
    path = _write(tmp_path, {"otp": {"enabled": False}})

    assert capability_enabled(load_capabilities_config(path), "otp") is False


def test_capability_explicitly_enabled_is_true(tmp_path: Path):
    path = _write(tmp_path, {"otp": {"enabled": True}})

    assert capability_enabled(load_capabilities_config(path), "otp") is True
```

- [ ] **Step 2: Run the tests and confirm they fail against today's code**

Run: `cd mcp_server && pytest tests/test_app_config.py -v`
Expected: many FAIL - `ImportError` for `capability_enabled`/`load_capabilities_config` (don't exist yet), and `KeyError: 'email'` / `KeyError: 'hosts'` / `KeyError: 'extensions'` from the old loaders trying to find a wrapper key that these unwrapped fixtures no longer have.

- [ ] **Step 3: Rewrite `infra/app_config.py`'s module docstring and `_require`**

Replace the module docstring (lines 1-57) with:

```python
"""Loaders for this server's JSON config files under src/configs/.

Three different kinds of configuration live in this project, deliberately
kept apart:

  - ``mcp_server/config.py`` - process settings read from environment
    variables (bind host/port, where the configs/secrets/data
    directories live). Small, flat, always present.
  - this file - structured, per-deployment data read from four JSON
    files under ``src/configs/`` (``settings.hosts_config_path`` /
    ``email_config_path`` / ``extensions_config_path`` /
    ``capabilities_config_path``): host inventories, mail settings,
    installed extensions, capability toggles. Too nested to be
    comfortable as env vars, and split one file per concern rather than
    one file with a section per concern, so each can be committed,
    diffed, and reasoned about on its own.
  - the environment - the actual secret *values*, which a config file
    only refers to by name (see below). Real values live under
    ``src/secrets/*.env``.

Each config file's top-level JSON *is* its content - ``config_hosts.json``
is ``{"zima": {...}, "desktop": {...}}`` directly, not
``{"hosts": {...}}``. There is no wrapper key to unwrap; ``load_config``
below just reads and parses one file, and every loader in this module
resolves the whole document (or, for hosts/extensions, one entry of it)
it gets handed.

A string anywhere in a config file may contain ``${VAR}``, which is
replaced with that environment variable's value::

    "password": "${SMTP_PASSWORD}"

That keeps every config file free of secrets - it names them instead of
holding them - while the values live in ``src/secrets/*.env`` in
development, or get injected by the service manager, container runtime,
or a secrets manager in production. Swapping that backend later means
changing how the environment gets populated, not any config file's
format and not any domain code.

Write ``$$`` for a literal ``$`` if a value genuinely needs to contain
``${...}`` text rather than have it substituted.

Substitution is *per entry* within ``config_hosts.json``/
``config_extensions.json`` (several hosts or extensions can share one
file), and over the *whole file* for ``config_email.json`` (there's only
one email config per file): each loader resolves only what it's about to
read, never eagerly. Resolving eagerly was the obvious implementation
and it was wrong - back when everything lived in one config.json, one
unset SSH password made an unrelated host, or even email, fail to load.
A deployment is allowed to have half its secrets present; only the half
it actually uses has to be.

Deliberately fails loudly, at load time, with a message naming the file
and the exact key - rather than returning ``{}`` or an empty string and
letting a capability fail much later with a confusing error deep inside
domain logic. The rule for which exception: ``KeyError`` when something
required is absent (a config key, an environment variable), ``ValueError``
when it's present but unusable (malformed JSON, an empty secret).

Add a loader function as capabilities need one, following
``load_email_config`` below: read the file, resolve it (or the one entry
you need) with ``resolve_section``, validate what's required, return a
frozen dataclass. Domain code should take that dataclass, never a raw
dict - that way a typo in a config file is caught here instead of at the
call site.
"""
```

Replace `_require`:

```python
def _require(section: dict[str, Any], key: str, *, prefix: str, config_path: Path) -> Any:
    if key not in section:
        full_key = f"{prefix}.{key}" if prefix else key
        raise KeyError(f"Config file {config_path} is missing '{full_key}'")
    return section[key]
```

- [ ] **Step 4: Rewrite `load_config`'s missing-file message**

```python
def load_config(config_path: Path) -> dict[str, Any]:
    """Read and parse one config file. Raises on anything unusable.

    Returns the document exactly as written, ``${VAR}`` placeholders and
    all; a loader resolves the part it needs with ``resolve_section``.
    """
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}. Copy {config_path.name}.example "
            f"to {config_path.name} in the same folder and fill it in."
        )
    try:
        with config_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as error:
        raise ValueError(f"Config file {config_path} is not valid JSON: {error}") from error

    if not isinstance(data, dict):
        raise ValueError(f"Config file {config_path} must contain a JSON object at the top level")
    return data
```

- [ ] **Step 5: Rewrite `load_email_config`**

```python
def load_email_config(config_path: Path) -> EmailConfig:
    """Parse config_email.json into an EmailConfig.

    ``from`` is a Python keyword, so it can't be a dataclass field name -
    it's read from the JSON as ``from`` and exposed as ``from_address``.

    ``password``, ``security``, ``to`` and ``allowed_recipient_domains``
    are the only optional keys. ``password`` is optional because an
    unauthenticated relay is a legitimate setup, not a mistake to guard
    against; ``security`` because the port already implies it in the
    common cases; ``allowed_recipient_domains`` because its absence is a
    *stricter* deployment, not an unconfigured one; ``to`` because a
    deployment that only ever mails caller-supplied addresses (see
    ``allowed_recipient_domains``) has no standing recipient list and
    shouldn't have to invent one to pass validation.
    """
    section = load_config(config_path)
    section = resolve_section(section, where="", config_path=config_path)

    def required(key: str) -> Any:
        return _require(section, key, prefix="", config_path=config_path)

    def as_string_list(value: Any) -> list[str]:
        # A bare string is the obvious thing to write for one recipient (or
        # one domain), and iterating it character-by-character would be a
        # nasty way to find out otherwise.
        if isinstance(value, str):
            value = [value]
        return [str(item) for item in value]

    # Empty is allowed and is not checked against `approver_emails` here.
    # `send_email` already refuses with "No recipients", and the OTP
    # capability raises its own KeyError naming the keys to add, so a
    # load-time failure would only forbid the legitimate config that sends
    # exclusively to addresses the caller names.
    recipients = as_string_list(section.get("to", []))
    approvers = as_string_list(section.get("approver_emails", recipients))

    domains = [
        normalize_recipient_domain(entry)
        for entry in as_string_list(section.get("allowed_recipient_domains", []))
    ]
    # A blank entry - the "" left behind by editing a JSON list - is
    # dropped rather than rejected. It can only ever fail to match, so
    # keeping it would widen nothing; all it would do is appear in the
    # refusal message a caller reads to work out what it should have said.
    domains = [domain for domain in domains if domain]

    port = int(required("smtp_port"))
    inferred = "ssl" if port == IMPLICIT_TLS_PORT else "starttls"
    security = str(section.get("security", inferred)).strip().lower()
    if security not in SUPPORTED_EMAIL_SECURITY:
        # No permissive fallback on a typo. Quietly downgrading "tls" to a
        # plaintext or unverified connection would send the password in the
        # clear, and nothing about the run would say so.
        raise ValueError(
            f"Config file {config_path}: 'security' is {security!r}, "
            f"expected one of {', '.join(SUPPORTED_EMAIL_SECURITY)}."
        )

    return EmailConfig(
        smtp_server=str(required("smtp_server")),
        smtp_port=port,
        from_address=str(required("from")),
        to=recipients,
        password=str(section.get("password", "")),
        security=security,
        approver_emails=approvers,
        allowed_recipient_domains=domains,
    )
```

- [ ] **Step 6: Rewrite the hosts loaders**

```python
SUPPORTED_HOST_OS = ("linux", "windows")


def _hosts_section(config_path: Path) -> dict[str, Any]:
    """The raw host-inventory mapping, placeholders still unresolved -
    config_hosts.json's whole content."""
    return load_config(config_path)


def _build_host(name: str, entry: Any, *, config_path: Path) -> HostConfig:
    """Resolve and validate one raw host entry into a HostConfig.

    The unit of resolution is deliberately a single entry: this is the
    whole reason one unreachable machine's missing secret no longer takes
    the others down with it. Both loaders go through here so that "one
    host" and "all hosts" cannot drift into validating differently - the
    single-host path is the one that runs in production, and it would be
    the one that quietly lost a check.
    """
    if not isinstance(entry, dict):
        raise ValueError(f"Config file {config_path}: '{name}' must be an object")

    # Resolved under the entry's own name, so the message still reads
    # 'desktop.password' and points at a findable line.
    entry = resolve_section(entry, where=name, config_path=config_path)

    def required(key: str) -> Any:
        return _require(entry, key, prefix=name, config_path=config_path)

    host_os = str(required("os")).strip().lower()
    if host_os not in SUPPORTED_HOST_OS:
        raise ValueError(
            f"Config file {config_path}: '{name}.os' is {host_os!r}, "
            f"expected one of {', '.join(SUPPORTED_HOST_OS)}."
        )

    key = entry.get("key")
    password = entry.get("password")
    if not key and not password:
        # Failing here beats failing at connect time, where it surfaces
        # as a generic auth error and looks like a wrong password.
        raise KeyError(f"Config file {config_path}: '{name}' needs a 'key' or a 'password'.")

    return HostConfig(
        name=name,
        hostname=str(required("hostname")),
        user=str(required("user")),
        os=host_os,
        port=int(entry.get("port", 22)),
        key=str(key) if key else None,
        password=str(password) if password else None,
    )


def load_hosts_config(config_path: Path) -> dict[str, HostConfig]:
    """Parse config_hosts.json into HostConfigs keyed by name.

    This one really does need every host's secrets present, because it
    claims to return every host - a caller listing the inventory would
    otherwise get a silently short list. Reach for ``load_host_config``
    when you only want one; that is the call that survives a broken
    sibling.
    """
    section = _hosts_section(config_path)
    return {name: _build_host(name, entry, config_path=config_path) for name, entry in section.items()}


def load_host_config(config_path: Path, name: str) -> HostConfig:
    """One host by name, with the available names listed if it's not there -
    the caller is usually a model that guessed, and the fix is knowing
    what it could have said instead.

    Only the named host's entry is resolved, so a ``desktop`` whose
    password variable is unset cannot stop you from reaching ``zima``.
    Loading all hosts and then indexing would read identically and defeat
    the entire point.
    """
    section = _hosts_section(config_path)
    if name not in section:
        # Names come from the JSON keys, which are never substituted, so
        # this list is available without resolving anything.
        known = ", ".join(sorted(section)) or "none configured"
        raise KeyError(f"Unknown host {name!r}. Configured hosts: {known}.")

    return _build_host(name, section[name], config_path=config_path)
```

- [ ] **Step 7: Rewrite the extensions loaders and save/delete**

```python
# --- extensions ----------------------------------------------------------
# Mirrors the "hosts" loaders immediately above: per-entry resolution, and
# a broken sibling can't take down the others.


def _extensions_section(config_path: Path) -> dict[str, Any]:
    """The raw extensions mapping, placeholders still unresolved -
    config_extensions.json's whole content."""
    return load_config(config_path)


def _build_extension(id_: str, entry: Any, *, config_path: Path) -> ExtensionConfig:
    """Resolve and validate one raw extension entry into an ExtensionConfig.

    Same reasoning as ``_build_host``: the unit of resolution is one
    entry, so an extension whose ``args`` names an unset ``${VAR}`` can't
    stop a working sibling from connecting.

    Transport is inferred from which of ``command``/``url`` the entry
    supplies, not from a separate ``transport`` key - the two are
    mutually exclusive ways to say "how do I reach this server", and a
    ``transport`` key that could disagree with them would just be
    another way for the config to be self-contradictory. Both present or
    both absent is rejected outright rather than guessed at.
    """
    if not isinstance(entry, dict):
        raise ValueError(f"Config file {config_path}: '{id_}' must be an object")

    entry = resolve_section(entry, where=id_, config_path=config_path)

    def required(key: str) -> Any:
        return _require(entry, key, prefix=id_, config_path=config_path)

    has_command = "command" in entry
    has_url = "url" in entry
    if has_command and has_url:
        raise ValueError(
            f"Config file {config_path}: '{id_}' has both 'command' and 'url' - "
            f"a stdio extension (spawned as a subprocess) uses 'command' and optionally "
            f"'args'; an http extension (already running elsewhere) uses 'url'. Remove one."
        )
    if not has_command and not has_url:
        raise ValueError(
            f"Config file {config_path}: '{id_}' needs either 'command' (to launch "
            f"a stdio extension) or 'url' (to connect to an already-running http extension)."
        )

    label = str(required("label"))
    description = str(entry.get("description", ""))

    if has_url:
        url = str(required("url")).strip()
        if not url:
            raise ValueError(f"Config file {config_path}: '{id_}.url' must not be empty")
        return ExtensionConfig(id=id_, label=label, description=description, transport="http", url=url)

    args = entry.get("args", [])
    if not isinstance(args, list):
        raise ValueError(f"Config file {config_path}: '{id_}.args' must be a list")

    return ExtensionConfig(
        id=id_,
        label=label,
        description=description,
        transport="stdio",
        command=str(required("command")),
        args=[str(item) for item in args],
    )


def load_extensions_config(config_path: Path) -> dict[str, ExtensionConfig]:
    """Parse config_extensions.json into ExtensionConfigs keyed by id.

    Called once at startup for the full set - see ``_build_extension``
    for why one broken entry doesn't stop the rest from loading.
    """
    section = _extensions_section(config_path)
    return {id_: _build_extension(id_, entry, config_path=config_path) for id_, entry in section.items()}


def load_extension_config(config_path: Path, id_: str) -> ExtensionConfig:
    """One extension by id, with the available ids listed if it's not
    there. Mirrors ``load_host_config``: only the named entry is
    resolved, so a broken sibling can't stop this one from loading."""
    section = _extensions_section(config_path)
    if id_ not in section:
        known = ", ".join(sorted(section)) or "none configured"
        raise KeyError(f"Unknown extension {id_!r}. Configured extensions: {known}.")

    return _build_extension(id_, section[id_], config_path=config_path)


def _write_config(config_path: Path, data: dict[str, Any]) -> None:
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def save_extension_config(config_path: Path, config: ExtensionConfig) -> None:
    """Insert or overwrite one entry in config_extensions.json, leaving
    every other entry untouched.

    Reads with ``load_config`` (not a loader that resolves placeholders),
    so an unrelated ``${VAR}`` in another extension's ``args`` passes
    through byte-for-byte instead of being baked in as its resolved
    value. ``config`` itself is expected to already hold whatever it
    wants written literally (this is the shape ``infra/extensions.py``'s
    runtime ``add_extension`` passes straight from an HTTP request body,
    which never contains ``${VAR}`` placeholders to begin with).

    Written by transport: a stdio config's ``command``/``args``, or for
    an http config just ``url``, so a re-read through
    ``load_extensions_config`` gets exactly what ``_build_extension``
    expects for that transport - no leftover empty ``command``/``url``
    from the other branch's field defaults.
    """
    data = load_config(config_path)

    entry: dict[str, Any] = {"label": config.label, "description": config.description}
    if config.transport == "http":
        entry["url"] = config.url
    else:
        entry["command"] = config.command
        entry["args"] = config.args
    data[config.id] = entry

    _write_config(config_path, data)


def delete_extension_config(config_path: Path, extension_id: str) -> None:
    """Remove one entry from config_extensions.json.

    Idempotent - removing an id that's already absent is not an error,
    since the caller's goal ("this id must not be configured") is
    already true.
    """
    data = load_config(config_path)
    data.pop(extension_id, None)
    _write_config(config_path, data)
```

- [ ] **Step 8: Add the capabilities loader**

Append to the end of the file:

```python
# --- capabilities ----------------------------------------------------------
# Which built-in capabilities (mcp_server/capabilities/<name>/) are
# enabled. Read once at startup by run.py, which skips a disabled
# capability's tool-registering import entirely - see that module.


def load_capabilities_config(config_path: Path) -> dict[str, dict[str, Any]]:
    """Read config_capabilities.json: which capabilities are enabled.

    Missing file -> {} (every capability enabled) rather than raising,
    unlike every loader above. Every capability was always enabled before
    this file existed, so a deployment that never creates it - or hasn't
    updated past this feature yet - must keep behaving exactly as it did,
    not fail to start.
    """
    if not config_path.exists():
        return {}
    return load_config(config_path)


def capability_enabled(config: dict[str, dict[str, Any]], name: str) -> bool:
    """True unless `name` is present in `config` with `"enabled": false`.

    A capability absent from the file - the common case, since most
    deployments only ever write down the one they want to turn *off* - is
    enabled. Widening that default (treating an unlisted capability as
    disabled) would mean every capability vanishes the moment this file
    is created for any reason, which is the toggle equivalent of the
    "absent extensions section" bug this same module used to have.
    """
    entry = config.get(name, {})
    if not isinstance(entry, dict):
        return True
    return bool(entry.get("enabled", True))
```

- [ ] **Step 9: Run the tests and confirm they pass**

Run: `cd mcp_server && pytest tests/test_app_config.py -v`
Expected: all PASS.

- [ ] **Step 10: Run the full suite to check for collateral damage**

Run: `cd mcp_server && pytest -v`
Expected: failures only in files this task didn't touch yet (`test_extensions.py`, `test_host_health_capability.py` - both call the loaders this task just changed, and are fixed in Tasks 2 and 5). Confirm no *other* file regressed.

- [ ] **Step 11: Commit**

```bash
git add mcp_server/src/mcp_server/infra/app_config.py mcp_server/tests/test_app_config.py
git commit -m "refactor: split app_config.py loaders into one file per concern, add capability toggle loader"
```

---

## Task 2: `Settings` gains `configs_dir` and the four `*_config_path` properties

**Files:**
- Modify: `mcp_server/src/mcp_server/config.py`

**Interfaces:**
- Produces: `settings.configs_dir: Path`, `settings.hosts_config_path: Path`, `settings.email_config_path: Path`, `settings.extensions_config_path: Path`, `settings.capabilities_config_path: Path`.
- Removes: `settings.config_path` (every remaining reader is fixed in Tasks 4-5).
- Unchanged: `settings.host`, `settings.port`, `settings.public_base_url`, `settings.ssh_known_hosts`, `settings.ssh_host_key_policy`, `settings.pending_requests_path`, `settings.otp_path`, `settings.log_dir` - same names, same env-var overrides, only three defaults change (see Step 1).

No test file exists for `config.py` today (`Settings` is exercised indirectly through every other test file's `dataclasses.replace(base_settings, ...)` calls, which only touch fields that keep their names) - this task has no new tests of its own.

- [ ] **Step 1: Rewrite `config.py`**

```python
"""Server-wide settings.

Deliberately plain (no external settings library required) - swap for
pydantic-settings later if the number of tunables grows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    """os.getenv, but an empty value counts as unset.

    ``os.getenv`` returns "" for a variable that's present but blank, so a
    commented-out-by-emptying line in .env (``SSH_KNOWN_HOSTS=``) would
    override the default with an empty string rather than leave it alone -
    which for a path means Path(""), i.e. the current directory. Blank
    almost always means "I didn't set this".
    """
    value = os.getenv(name)
    return value if value else default


@dataclass(frozen=True)
class Settings:
    # Where the four config_*.json files (see infra/app_config.py) live.
    # Relative to CWD by default, same fragile-by-default convention as
    # every path below - mcp_server is always run from its own directory
    # (run_mcp_server.bat cd's there first), so "src/configs" resolves.
    configs_dir: Path = Path(_env("MCP_CONFIGS_DIR", "src/configs"))
    # Loopback by default, deliberately. This server has no authentication
    # of its own: anything that can reach the port can call every
    # registered tool with arbitrary arguments, and the Flask app is not
    # in that path, so no amount of auth over there protects this. Binding
    # to 0.0.0.0 exposes that to the whole network, which should be a
    # decision someone makes on purpose rather than a default they
    # inherit. Override MCP_HOST only once something in front of it
    # (reverse proxy, VPN, firewall) is doing the authenticating.
    host: str = _env("MCP_HOST", "127.0.0.1")
    port: int = int(_env("MCP_PORT", "8010"))
    # SQLite file backing infra/pending_requests.py - relative to CWD by
    # default (kept fragile-by-default rather than fixed only here).
    # Backs any approval-gated / resumable capability, not tied to any
    # specific one, so it lives under the general src/data/ rather than
    # inside any single capabilities/<name>/ folder.
    pending_requests_path: Path = Path(_env("PENDING_REQUESTS_PATH", "src/data/pending_requests.db"))
    # SQLite file backing infra/otp.py - relative to CWD by default, same
    # as pending_requests_path above. Defaults inside capabilities/otp/,
    # the one capability that owns this file - unlike
    # pending_requests_path, nothing else ever reads or writes it. Only
    # the path is a setting: code length, TTL and the attempt limit stay
    # constants in infra/otp.py, because they are what makes a six-digit
    # secret safe and an env var is too easy a place to weaken them from.
    otp_path: Path = Path(
        _env("OTP_PATH", "src/mcp_server/capabilities/otp/data/otp.db")
    )
    # The URL an approval email's link points at. Deliberately NOT derived
    # from host/port above - `host` is a bind address (127.0.0.1 and
    # 0.0.0.0 are both meaningless from someone else's inbox), while this
    # needs to be whatever address actually resolves for an approver (a
    # VPN hostname, a reverse-proxy address, etc). Defaults to localhost
    # so this works out of the box for local testing; override for any
    # real deployment.
    public_base_url: str = _env("MCP_PUBLIC_BASE_URL", "http://127.0.0.1:8010")
    # known_hosts file used to verify SSH host keys. Defaults to the same
    # one the ssh command-line client uses, so hosts you've already
    # connected to from this machine are trusted without extra setup.
    ssh_known_hosts: Path = Path(
        _env("SSH_KNOWN_HOSTS", str(Path.home() / ".ssh" / "known_hosts"))
    )
    # "reject" (default) or "auto". Rejecting an unknown host key is the
    # point of having known_hosts at all: it's what makes a
    # machine-in-the-middle visible, and - more importantly in practice -
    # what makes a host key that *changed* an error instead of a silent
    # accept. "auto" trusts whatever key answers first and records it,
    # which is fine for a throwaway lab and wrong everywhere else.
    ssh_host_key_policy: str = _env("SSH_HOST_KEY_POLICY", "reject")
    # Where logging_setup.configure_logging() writes server.log and
    # errors.report() writes per-reference error files. Relative to CWD by
    # default, same convention as the paths above.
    log_dir: Path = Path(_env("MCP_LOG_DIR", "src/logs"))

    @property
    def hosts_config_path(self) -> Path:
        return self.configs_dir / "config_hosts.json"

    @property
    def email_config_path(self) -> Path:
        return self.configs_dir / "config_email.json"

    @property
    def extensions_config_path(self) -> Path:
        return self.configs_dir / "config_extensions.json"

    @property
    def capabilities_config_path(self) -> Path:
        return self.configs_dir / "config_capabilities.json"


settings = Settings()
```

- [ ] **Step 2: Run the full suite**

Run: `cd mcp_server && pytest -v`
Expected: same failures as Task 1's Step 10 (files this change's callers live in, fixed next), plus now also failures in any file that referenced `settings.config_path` directly - confirm the failures are all `AttributeError: 'Settings' object has no attribute 'config_path'` or import errors, nothing else new.

- [ ] **Step 3: Commit**

```bash
git add mcp_server/src/mcp_server/config.py
git commit -m "refactor: replace Settings.config_path with configs_dir + four config path properties"
```

---

## Task 3: Directory scaffolding - `src/configs/`, `src/secrets/`, `src/data/`, `src/logs/`

**Files:**
- Create: `mcp_server/src/configs/config_hosts.json`, `.example`
- Create: `mcp_server/src/configs/config_email.json`, `.example`
- Create: `mcp_server/src/configs/config_extensions.json`, `.example`
- Create: `mcp_server/src/configs/config_capabilities.json`, `.example`
- Create: `mcp_server/src/secrets/secret_app.env`, `.example`
- Create: `mcp_server/src/secrets/secret_smtp.env`, `.example`
- Create: `mcp_server/src/secrets/secret_ssh.env`, `.example`
- Delete: `mcp_server/config.json`, `mcp_server/config.json.example`, `mcp_server/.env`, `mcp_server/.env.example`, `mcp_server/data/` (only `otp.db`, moved in Task 5), `mcp_server/logs/`
- Modify: `.gitignore` (repo root)

**Interfaces:** none - this task only moves files and data around; no code changes. `src/data/` and `src/logs/` are created empty (populated at runtime by `pending_requests.py`/`logging_setup.py`, both of which already `mkdir(parents=True, exist_ok=True)` their target directory).

- [ ] **Step 1: Create `src/configs/` with real values migrated from `config.json`**

`mcp_server/src/configs/config_hosts.json` (real value, from the current `config.json`'s `"hosts"` section):

```json
{
  "zima": {
    "hostname": "192.168.1.9",
    "user": "lex",
    "os": "linux",
    "key": "C:/Users/User/.ssh/id_ed25519",
    "password": "${ZIMA_SSH_PASSWORD}"
  }
}
```

`mcp_server/src/configs/config_hosts.json.example`:

```json
{
  "zima": {
    "hostname": "127.0.0.1",
    "user": "root",
    "os": "linux",
    "key": "/root/.ssh/id_ed25519"
  },
  "desktop": {
    "hostname": "192.168.1.20",
    "user": "YourWindowsUser",
    "os": "windows",
    "password": "${DESKTOP_SSH_PASSWORD}"
  }
}
```

`mcp_server/src/configs/config_email.json` (real value):

```json
{
  "smtp_server": "smtp.gmail.com",
  "smtp_port": 465,
  "security": "ssl",
  "from": "ember.notifications.pro@gmail.com",
  "password": "${SMTP_PASSWORD}",
  "approver_emails": [
    "scutiii.code@gmail.com",
    "johnlexterpanti@gmail.com"
  ]
}
```

`mcp_server/src/configs/config_email.json.example`:

```json
{
  "smtp_server": "smtp.gmail.com",
  "smtp_port": 465,
  "security": "ssl",
  "from": "you@gmail.com",
  "password": "${SMTP_PASSWORD}",
  "approver_emails": ["you@gmail.com"]
}
```

`mcp_server/src/configs/config_extensions.json` (real value - empty, matching today's deployment):

```json
{}
```

`mcp_server/src/configs/config_extensions.json.example`:

```json
{
  "reference": {
    "_comment": "Dev fixture proving the extension-proxy mechanism, not a real integration - see src/mcp_server/_fixtures/reference_extension_server.py. 'command' below is this repo's own venv; point it at your own venv's python for any real extension. This is the stdio transport: this server spawns 'command' as a local subprocess and talks MCP to it over stdin/stdout.",
    "label": "Reference Extension (dev fixture)",
    "description": "Two trivial tools (echo, add) used to prove infra/extensions.py's proxy mechanism works end to end.",
    "command": "venv_mcp/Scripts/python.exe",
    "args": ["-m", "mcp_server._fixtures.reference_extension_server"]
  },
  "example-http": {
    "_comment": "Example of the http transport: an MCP server that's already running somewhere else, reached over streamable HTTP instead of spawned as a subprocess - 'url' is that server's MCP endpoint. An extension entry has either 'command' (stdio, above) or 'url' (http, here), never both. This same shape is also what POST /extensions creates at runtime (see extension_routes.py) - hand-edit it here, or add it live through that route; both end up in this same file.",
    "label": "Example HTTP Extension",
    "description": "An already-running MCP server reached over HTTP instead of launched as a subprocess.",
    "url": "http://127.0.0.1:9000/mcp"
  }
}
```

`mcp_server/src/configs/config_capabilities.json` (real value - both currently in use, both enabled):

```json
{
  "host_health": { "enabled": true },
  "otp": { "enabled": true }
}
```

`mcp_server/src/configs/config_capabilities.json.example`:

```json
{
  "host_health": { "enabled": true },
  "otp": { "enabled": true }
}
```

- [ ] **Step 2: Create `src/secrets/` with real values migrated from `.env`**

`mcp_server/src/secrets/secret_app.env` (real value, from the current `.env`'s non-credential settings):

```
MCP_HOST = 127.0.0.1
MCP_PORT = 8010

MCP_PUBLIC_BASE_URL = http://127.0.0.1:8010
```

`mcp_server/src/secrets/secret_app.env.example`:

```
# Copy to secret_app.env in this same folder and fill in real values.
#
# Optional - defaults shown.
#
# MCP_HOST is loopback on purpose. This server has NO authentication:
# anything that can reach the port can call every registered tool with
# arbitrary arguments, and the Flask app is not in that path, so auth
# there does not protect this. Only set 0.0.0.0 once something in front
# of it (reverse proxy, VPN, firewall) is doing the authenticating.
MCP_HOST=127.0.0.1
MCP_PORT=8010

# The address an approval email's link should point at. Deliberately not
# derived from MCP_HOST above: 0.0.0.0 is a bind address, not something
# that resolves from someone's inbox. Set this to a real VPN or
# reverse-proxy hostname for any deployment beyond local testing.
MCP_PUBLIC_BASE_URL=http://127.0.0.1:8010
```

`mcp_server/src/secrets/secret_smtp.env` (real value):

```
SMTP_PASSWORD = @98paFne1jK23
```

`mcp_server/src/secrets/secret_smtp.env.example`:

```
# Copy to secret_smtp.env in this same folder and fill in a real value.
#
# Backs "password" in config_email.json. On a mainstream provider
# (Gmail, Outlook, Yahoo, iCloud) this must be an app-specific password,
# not the account password: they all refuse plain SMTP logins on an
# account with 2FA enabled.
#
# If the relay wants no authentication at all - a local or LAN MTA that
# authorizes by source address, usually with "security": "none" in
# config_email.json - drop the "password" key from config_email.json
# entirely and delete this line. Leaving it blank is NOT the way to do
# that: a "${SMTP_PASSWORD}" placeholder resolving to an empty string is
# rejected at load time, because in practice that means someone forgot
# to fill it in rather than meaning "no auth".
SMTP_PASSWORD=
```

`mcp_server/src/secrets/secret_ssh.env` (real value):

```
ZIMA_SSH_PASSWORD = @PantiServer061726

SSH_HOST_KEY_POLICY = reject
```

`mcp_server/src/secrets/secret_ssh.env.example`:

```
# Copy to secret_ssh.env in this same folder and fill in real values.
#
# One VAR per host entry in config_hosts.json that authenticates with a
# password instead of a key - name it whatever config_hosts.json's
# "password": "${...}" placeholder names.
DESKTOP_SSH_PASSWORD=
ZIMA_SSH_PASSWORD=

# SSH host-key verification. "reject" (default) refuses a host whose key
# isn't in the known_hosts file below - which is mainly how you find out
# a key CHANGED, the signal that actually matters. "auto" trusts the
# first key it sees and records it, so you can enrol a new host that way
# and then switch back to reject.
SSH_HOST_KEY_POLICY=reject
SSH_KNOWN_HOSTS=
```

- [ ] **Step 3: Delete the old root-level files and directories**

```bash
cd mcp_server
git rm --cached -f .env config.json 2>/dev/null || true
rm -f .env .env.example config.json config.json.example
rm -rf data logs
```

(`.env`/`config.json` were already gitignored, hence `git rm --cached` failing silently is fine if they were never tracked - `|| true` covers that. `data/otp.db` is short-lived OTP state, ten-minute TTL - nothing worth preserving. `pending_requests.db` never existed at the root, per the earlier repo scan - no approval has been requested yet in this deployment.)

- [ ] **Step 4: Create empty `src/data/` and `src/logs/` placeholders**

Git does not track empty directories; `infra/pending_requests.py`'s `_connect()` and `logging_setup.py`'s `configure_logging()` both already `mkdir(parents=True, exist_ok=True)` their target directory on first use, so nothing needs to exist on disk yet - Task 6's README is the only file that needs to land in `src/data/` before it's a real directory in git.

- [ ] **Step 5: Update the repo-root `.gitignore`**

Read the current file first (`D:\User\Documents\Programming\Python\MCPServer\.gitignore`) to confirm line numbers haven't shifted, then replace:

```
.env
config.json
__pycache__/
*.pyc
.venv/
venv_*/
*.egg-info/

# Runtime state, not source: pending approval requests and one-time-code
# records. Both hold security-relevant material - an approval token is a
# live authorization until it expires, and the OTP rows are salted
# hashes. Neither belongs in version control.
*.db

# Runtime logs: combined server.log plus one file per error reference id
# (see chat_app/mcp_server's logging_setup.py / errors.py). Regenerated
# on every run, not source. Anchored to each app's own root (not a bare
# "logs/") - unanchored, this also matched chat_app's SOURCE blueprint at
# pages/logs/, silently excluding it from version control entirely.
/chat_app/logs/
/mcp_server/logs/
```

with:

```
__pycache__/
*.pyc
.venv/
venv_*/
*.egg-info/

# mcp_server's real config/secrets/runtime-state, mirroring chat_app's
# src/configs + src/secrets + src/data split. config_*.json holds
# structure (committed) with ${VAR} placeholders for anything sensitive;
# secret_*.env holds the real values (gitignored) those placeholders
# resolve to. Both keep an .example twin, which IS committed.
/mcp_server/src/secrets/*
!/mcp_server/src/secrets/*.example
!/mcp_server/src/secrets/README.md

# mcp_server's real host inventory and approver/SMTP-account addresses.
# The equivalent data lived in the old root-level config.json, which was
# gitignored outright - these two carry the same real deployment details
# (no literal secrets, those are all ${VAR}) and keep the same treatment.
# config_extensions.json and config_capabilities.json are NOT listed
# here - low-sensitivity structure, tracked normally like their
# .example twins.
/mcp_server/src/configs/config_hosts.json
/mcp_server/src/configs/config_email.json

# Runtime state, not source: pending approval requests, one-time-code
# records, and any capability's own data/ (e.g. capabilities/otp/data/).
# All hold security-relevant material or are regenerated on every run.
/mcp_server/src/data/*
!/mcp_server/src/data/README.md
*.db

# Runtime logs: combined server.log plus one file per error reference id
# (see chat_app/mcp_server's logging_setup.py / errors.py). Regenerated
# on every run, not source. Anchored to each app's own root (not a bare
# "logs/") - unanchored, this also matched chat_app's SOURCE blueprint at
# pages/logs/, silently excluding it from version control entirely.
/chat_app/logs/
/mcp_server/src/logs/
```

(`config_hosts.json`/`config_email.json` are ignored by exact path, matching how the root-level `config.json` they replace was already gitignored outright before this change - they carry this deployment's real host list and approver/SMTP-account addresses, even though the `${VAR}` mechanism keeps any literal secret out of them. `config_extensions.json`/`config_capabilities.json` are deliberately NOT in that list: today's real values (`{}` and both capabilities enabled) are unremarkable and worth tracking normally, same as their `.example` twins - a future deployment with a genuinely sensitive extension entry can gitignore its own `config_extensions.json` locally without this repo needing to. `*.db` stays as a global safety net alongside the anchored `src/data/*` line, so `capabilities/otp/data/otp.db` is ignored no matter where a future capability's own data directory ends up.)

- [ ] **Step 6: Verify the new files are ignored (or not) where intended**

Run: `cd "D:\User\Documents\Programming\Python\MCPServer" && git status --short mcp_server/`
Expected: `config_hosts.json`, `config_email.json`, and all three `secret_*.env` files do NOT appear (ignored); the six `.example` files, `config_extensions.json`, and `config_capabilities.json` DO appear as untracked, ready to be added in Step 7.

- [ ] **Step 7: Commit**

```bash
cd "D:\User\Documents\Programming\Python\MCPServer"
git add .gitignore mcp_server/src/configs/*.example mcp_server/src/configs/config_extensions.json \
        mcp_server/src/configs/config_capabilities.json mcp_server/src/secrets/*.example
git status
```

Confirm `config_hosts.json`, `config_email.json`, and every `secret_*.env` are absent from the staged list (still gitignored, by design - do not `-f` them in). Then:

```bash
git commit -m "chore: scaffold mcp_server/src/configs and src/secrets, migrate real config.json/.env values, remove old root files"
```

---

## Task 4: Capability toggle wiring in `run.py`

**Files:**
- Modify: `mcp_server/src/mcp_server/run.py`

**Interfaces:**
- Consumes: `load_capabilities_config(settings.capabilities_config_path)` and `capability_enabled(config, name)` from Task 1.
- Consumes: `settings.extensions_config_path` (Task 2) in place of `settings.config_path`.

`run.py` has no dedicated test file today (it's the process entry point, exercised by actually starting the server) - this task is verified by running the server manually per Step 4, not by pytest.

- [ ] **Step 1: Rewrite the imports and secrets-loading section**

Replace lines 1-18 (from the module docstring through `configure_logging(settings.log_dir)`):

```python
"""Entry point for the MCP server.

Run with:
    python -m mcp_server.run
"""

from __future__ import annotations

from pathlib import Path

# Must run before any mcp_server.* import: Settings' field defaults read
# os.getenv() at class-definition time (i.e. at import time), so every
# secrets/*.env file needs to be loaded into the environment first or
# those defaults never see it. Loaded from every *.env file in
# src/secrets/ rather than one fixed name, mirroring src/configs/'s
# one-file-per-concern split (secret_app.env, secret_smtp.env,
# secret_ssh.env today; a future capability that owns a real secret adds
# its own file here with zero changes to this loop).
from dotenv import load_dotenv

_SECRETS_DIR = Path("src/secrets")
for _env_file in sorted(_SECRETS_DIR.glob("*.env")):
    load_dotenv(_env_file)

from mcp_server.config import settings  # noqa: E402
from mcp_server.infra.app_config import capability_enabled, load_capabilities_config  # noqa: E402
from mcp_server.logging_setup import configure_logging  # noqa: E402
from mcp_server.server import mcp  # noqa: E402

# Before anything else runs, so uvicorn's own request/error logging (once
# it starts inside _serve() below) is captured on disk from the start,
# not just log lines written after some later point in startup.
configure_logging(settings.log_dir)

_capabilities_config = load_capabilities_config(settings.capabilities_config_path)
```

- [ ] **Step 2: Gate the capability imports**

Replace the current unconditional import block:

```python
from mcp_server.capabilities.host_health import tool as host_health_tool  # noqa: E402,F401
from mcp_server.capabilities.otp import tool as otp_tool  # noqa: E402,F401
from mcp_server.resources.host_health import resource as host_health_resource  # noqa: E402,F401
```

with:

```python
# Import order = the order tools/resources appear in their respective
# list calls. Add each new capability's tool/resource module here as it's
# built, following the pattern in capabilities/<name>/ (contract.py /
# domain.py / tool.py) described in the README's "Adding a new tool"
# section - and add a toggle entry to config_capabilities.json /
# config_capabilities.json.example.
#
# Importing a capability's tool/resource module is what runs its
# @mcp.tool()/@mcp.resource() decorator and registers it - so skipping
# the import, when config_capabilities.json disables it, is the entire
# mechanism: a disabled capability never appears in list_tools(),
# /commands, or chat_app's capabilities page.
#
# host_health appears twice on purpose when enabled: the resource serves
# clients that read a URI, the capability serves models that can only see
# tools. Same domain logic underneath, same toggle entry governs both -
# see capabilities/host_health/domain.py.
_enabled_capabilities: list[str] = []
if capability_enabled(_capabilities_config, "host_health"):
    from mcp_server.capabilities.host_health import tool as host_health_tool  # noqa: E402,F401
    from mcp_server.resources.host_health import resource as host_health_resource  # noqa: E402,F401

    _enabled_capabilities.append("host_health")
if capability_enabled(_capabilities_config, "otp"):
    from mcp_server.capabilities.otp import tool as otp_tool  # noqa: E402,F401

    _enabled_capabilities.append("otp")
```

- [ ] **Step 3: Update the banner**

In `_serve()`, replace:

```python
        banner = [
            "MCP server",
            f"  Endpoint : http://{settings.host}:{settings.port}/mcp",
            f"  Config   : {settings.config_path}",
            f"  Tools    : {len(tool_names)}",
            *(f"    - {name}" for name in tool_names),
            f"  Resources: {resource_count}",
            f"  Gated    : {', '.join(approvals.registered_names()) or 'none'}",
            f"  Extensions: {', '.join(f'{s.id} ({s.status})' for s in extension_statuses) or 'none'}",
        ]
```

with:

```python
        banner = [
            "MCP server",
            f"  Endpoint : http://{settings.host}:{settings.port}/mcp",
            f"  Config   : {settings.configs_dir}",
            f"  Capabilities: {', '.join(sorted(_enabled_capabilities)) or 'none'}",
            f"  Tools    : {len(tool_names)}",
            *(f"    - {name}" for name in tool_names),
            f"  Resources: {resource_count}",
            f"  Gated    : {', '.join(approvals.registered_names()) or 'none'}",
            f"  Extensions: {', '.join(f'{s.id} ({s.status})' for s in extension_statuses) or 'none'}",
        ]
```

And replace `extensions.install_extensions(mcp, settings.config_path)` with `extensions.install_extensions(mcp, settings.extensions_config_path)`.

- [ ] **Step 4: Start the server manually and read the banner**

Run: `cd mcp_server && python -m mcp_server.run` (or `run_mcp_server.bat` from the repo root)
Expected: banner prints `Capabilities: host_health, otp`, `Config   : src/configs`, `Tools    : 3` listing `get_host_health_tool`, `request_otp_tool`, `verify_otp_tool`. Stop the server (Ctrl+C) once confirmed - this is the user's own manual verification step per their stated preference, not something to automate further.

- [ ] **Step 5: Toggle one capability off and confirm it disappears**

Edit `mcp_server/src/configs/config_capabilities.json` to `{"host_health": {"enabled": false}, "otp": {"enabled": true}}`, restart the server, confirm the banner now reads `Capabilities: otp` and `Tools    : 2` (no `get_host_health_tool`). Restore it to both `true` afterward.

- [ ] **Step 6: Commit**

```bash
git add mcp_server/src/mcp_server/run.py
git commit -m "feat: load src/secrets/*.env and gate capability imports behind config_capabilities.json"
```

---

## Task 5: Fix every remaining `settings.config_path` call site

**Files:**
- Modify: `mcp_server/src/mcp_server/infra/approvals.py`
- Modify: `mcp_server/src/mcp_server/extension_routes.py`
- Modify: `mcp_server/src/mcp_server/capabilities/host_health/domain.py`
- Modify: `mcp_server/src/mcp_server/capabilities/host_health/tool.py`
- Modify: `mcp_server/src/mcp_server/capabilities/otp/tool.py`
- Modify: `mcp_server/src/mcp_server/resources/host_health/resource.py`
- Move: `mcp_server/data/otp.db` state is not preserved (see Task 3 Step 3) - `mcp_server/src/mcp_server/capabilities/otp/data/` is created fresh by `infra/otp.py`'s `_connect()` on first use.
- Modify: `mcp_server/tests/test_extensions.py`
- Modify: `mcp_server/tests/test_host_health_capability.py`

**Interfaces:**
- Consumes: `settings.hosts_config_path`, `settings.email_config_path`, `settings.extensions_config_path` (Task 2).

- [ ] **Step 1: `infra/approvals.py`**

Change:

```python
    email_config = load_email_config(config_path or settings.config_path)
```

to:

```python
    email_config = load_email_config(config_path or settings.email_config_path)
```

(the function's own `config_path: Path | None = None` parameter name is unchanged - it's a generic override, and no caller currently passes it.)

- [ ] **Step 2: `extension_routes.py`**

Change:

```python
    status = await extensions.add_extension(config, settings.config_path)
```

to:

```python
    status = await extensions.add_extension(config, settings.extensions_config_path)
```

and:

```python
    removed = await extensions.remove_extension(extension_id, settings.config_path)
```

to:

```python
    removed = await extensions.remove_extension(extension_id, settings.extensions_config_path)
```

- [ ] **Step 3: `capabilities/host_health/domain.py`**

Change `known_host_names`:

```python
def known_host_names(config_path: Path) -> list[str]:
    """Configured host names, without resolving any placeholders.

    Names are JSON keys, so they are readable from the unresolved
    document. Going through ``load_hosts_config`` here would fail whenever
    *any* host had an unset secret, and the one moment this is called is
    when someone already got a name wrong - failing then would replace a
    helpful message with a confusing one.
    """
    return sorted(load_config(config_path))
```

(drops the `.get("hosts")` - `config_hosts.json`'s whole content already *is* the hosts mapping, per Task 1.)

- [ ] **Step 4: `capabilities/host_health/tool.py`**

Change:

```python
    return domain.check(settings.config_path, name)
```

to:

```python
    return domain.check(settings.hosts_config_path, name)
```

- [ ] **Step 5: `capabilities/otp/tool.py`**

Change:

```python
    email_config = load_email_config(settings.config_path)
```

to:

```python
    email_config = load_email_config(settings.email_config_path)
```

(`settings.otp_path` on the next line is unchanged - Task 2 only changed its default.)

- [ ] **Step 6: `resources/host_health/resource.py`**

Change:

```python
    config = load_host_config(settings.config_path, name)
```

to:

```python
    config = load_host_config(settings.hosts_config_path, name)
```

Also update its docstring line `` `name` is the key under "hosts" in config.json, not a hostname.`` to `` `name` is a key in config_hosts.json, not a hostname.``

- [ ] **Step 7: Fix `test_extensions.py`'s one config-shape test**

In `test_real_fixture_server_end_to_end`, change:

```python
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "extensions": {
                    "reference": {
                        "label": "Reference Extension (dev fixture)",
                        "description": "Dev fixture",
                        "command": sys.executable,
                        "args": ["-m", "mcp_server._fixtures.reference_extension_server"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
```

to:

```python
    config_path = tmp_path / "config_extensions.json"
    config_path.write_text(
        json.dumps(
            {
                "reference": {
                    "label": "Reference Extension (dev fixture)",
                    "description": "Dev fixture",
                    "command": sys.executable,
                    "args": ["-m", "mcp_server._fixtures.reference_extension_server"],
                }
            }
        ),
        encoding="utf-8",
    )
```

(`registry.connect_all(config_path)` below is unchanged - it already takes a path.)

- [ ] **Step 8: Fix `test_host_health_capability.py`'s config-shape fixture**

Change the `_config` helper:

```python
def _config(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"hosts": HOSTS}), encoding="utf-8")
    return path
```

to:

```python
def _config(tmp_path: Path) -> Path:
    path = tmp_path / "config_hosts.json"
    path.write_text(json.dumps(HOSTS), encoding="utf-8")
    return path
```

Replace `test_no_hosts_section_says_so_rather_than_listing_nothing`:

```python
def test_no_hosts_section_says_so_rather_than_listing_nothing(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"email": {}}), encoding="utf-8")

    with pytest.raises(KeyError, match="No hosts are configured"):
        domain.check(path, "zima")
```

with:

```python
def test_empty_hosts_file_says_so_rather_than_listing_nothing(tmp_path: Path):
    """config_hosts.json's whole content *is* the hosts map now, so an
    empty "{}" - a fresh install with no host inventory yet - is the
    "no hosts configured" state, not a malformed document."""
    path = tmp_path / "config_hosts.json"
    path.write_text(json.dumps({}), encoding="utf-8")

    with pytest.raises(KeyError, match="No hosts are configured"):
        domain.check(path, "zima")
```

- [ ] **Step 9: Run the full suite**

Run: `cd mcp_server && pytest -v`
Expected: all PASS. This is the first point in the plan where the entire suite is green again.

- [ ] **Step 10: Commit**

```bash
git add mcp_server/src/mcp_server/infra/approvals.py mcp_server/src/mcp_server/extension_routes.py \
        mcp_server/src/mcp_server/capabilities/host_health/domain.py \
        mcp_server/src/mcp_server/capabilities/host_health/tool.py \
        mcp_server/src/mcp_server/capabilities/otp/tool.py \
        mcp_server/src/mcp_server/resources/host_health/resource.py \
        mcp_server/tests/test_extensions.py mcp_server/tests/test_host_health_capability.py
git commit -m "refactor: point every settings.config_path reader at its specific *_config_path property"
```

---

## Task 6: `otp.db` moves inside `capabilities/otp/`

**Files:**
- Create: `mcp_server/src/mcp_server/capabilities/otp/data/README.md` (via Task 7's README pass - referenced here, written there)
- No code change: `settings.otp_path`'s new default (Task 2, Step 1) already points at `src/mcp_server/capabilities/otp/data/otp.db`; `infra/otp.py`'s `_connect()` already does `db_path.parent.mkdir(parents=True, exist_ok=True)`, so the directory is created automatically on first OTP request.

**Interfaces:** none new - this task is a verification-only checkpoint, folded in here rather than given its own commit, since Task 2 already did the actual change.

- [ ] **Step 1: Confirm the new default resolves and creates the directory**

Run:

```bash
cd mcp_server
python -c "from mcp_server.infra import otp; from mcp_server.config import settings; otp.create(settings.otp_path, 'test@example.com')"
```

Expected: no error, and `mcp_server/src/mcp_server/capabilities/otp/data/otp.db` now exists on disk (check with `ls mcp_server/src/mcp_server/capabilities/otp/data/`). Delete the test file afterward: `rm mcp_server/src/mcp_server/capabilities/otp/data/otp.db`.

- [ ] **Step 2: No commit for this task** - it verifies Task 2's change rather than introducing a new one. Proceed to Task 7, which adds the `.gitkeep`-equivalent README that makes this directory (and `src/data/`) exist in git before anything runs.

---

## Task 7: READMEs for every new directory and capability

**Files:**
- Create: `mcp_server/README.md`
- Create: `mcp_server/src/configs/README.md`
- Create: `mcp_server/src/secrets/README.md`
- Create: `mcp_server/src/data/README.md`
- Create: `mcp_server/src/mcp_server/capabilities/host_health/README.md`
- Create: `mcp_server/src/mcp_server/capabilities/otp/README.md`
- Modify: `mcp_server/src/mcp_server/capabilities/__init__.py`

**Interfaces:** none - documentation only. `src/data/README.md` is what makes `src/data/` exist in git despite Task 3's `.gitignore` pattern ignoring everything else under it; no equivalent file is needed for `capabilities/otp/data/` since that directory is created at runtime and never committed at all (see Task 6).

- [ ] **Step 1: `mcp_server/README.md`**

```markdown
# mcp_server

A general-purpose MCP (Model Context Protocol) tool server: SSH host
health checks, email one-time-passcode verification, a human-approval
gate for irreversible actions, and a proxy for other MCP servers'
tools ("extensions"). Built to be called by `chat_app` or any other MCP
client speaking streamable HTTP.

## Requirements

- Python >= 3.11
- An SMTP account for outbound mail (OTP codes, approval-request emails)
- (optional) one or more SSH-reachable hosts for the host-health capability

## Setup

1. From `mcp_server/`, install dependencies:

   ```
   pip install -e ".[dev]"
   ```

2. Copy the `.example` files under `src/secrets/` and `src/configs/` and
   fill in real values - see [Configuration](#configuration).

3. Run the server:

   ```
   run_mcp_server.bat
   ```

   (from the repo root; activates `venv_mcp` and runs `py -m mcp_server.run`.)

## Configuration

Both loaded once at boot by `src/mcp_server/run.py`:

- **`src/secrets/*.env`** - credentials, gitignored. Copy each
  `*.env.example` to the matching `*.env`. See
  [`src/secrets/README.md`](src/secrets/README.md).
- **`src/configs/*.json`** - structure, mostly committed. See
  [`src/configs/README.md`](src/configs/README.md).

## Capabilities

Each tool this server offers lives under its own folder in
`src/mcp_server/capabilities/`, with its own README:

- [`capabilities/host_health/README.md`](src/mcp_server/capabilities/host_health/README.md)
- [`capabilities/otp/README.md`](src/mcp_server/capabilities/otp/README.md)

Every capability can be turned off without touching code - see
`src/configs/README.md`'s section on `config_capabilities.json`.

## Runtime state

- **`src/data/README.md`** - state shared across capabilities.
- Each capability's own `data/` folder (e.g.
  `capabilities/otp/data/`), when it has one - documented in that
  capability's own README.
- **`src/logs/`** - `server.log` plus one file per error reference id,
  regenerated on every run.

## Tests

```
pytest
```

## Docker

See `zima_host.yaml` for a ZimaOS "customized app" Docker Compose recipe.
```

- [ ] **Step 2: `mcp_server/src/configs/README.md`**

```markdown
# src/configs/

Structured, per-deployment settings - host inventories, mail settings,
installed extensions, capability toggles. Loaded by
`infra/app_config.py` (see that module's docstring for the full loader
mechanics); paths come from `Settings.hosts_config_path` /
`email_config_path` / `extensions_config_path` /
`capabilities_config_path` in `config.py`.

- **`config_hosts.json`** - one entry per SSH-reachable host, keyed by
  the short name a tool call or `host://health/{name}` resource uses.
  Read by the `host_health` capability.
- **`config_email.json`** - SMTP settings and the standing
  recipient/approver lists. Read by the `otp` capability and by
  `infra/approvals.py` (approval-request emails).
- **`config_extensions.json`** - other MCP servers this server proxies
  tools from (see `infra/extensions.py`). Also written to at runtime by
  `POST`/`DELETE /extensions` (see `extension_routes.py`) - hand-edit it
  or add an extension live through that route, both end up here.
- **`config_capabilities.json`** - which built-in capabilities
  (`host_health`, `otp`) are enabled. A capability absent from this file
  is enabled; only an explicit `{"enabled": false}` turns one off:

  ```json
  { "host_health": { "enabled": true }, "otp": { "enabled": false } }
  ```

  Read once at startup by `run.py`, which skips a disabled capability's
  tool-registering import entirely - it won't appear in `list_tools()`,
  `/commands`, or chat_app's capabilities page. Restart the server for a
  change to take effect.

Each file's top-level JSON *is* its content - there's no wrapper key.
Anything sensitive is a `${VAR}` placeholder resolved from
`../secrets/*.env` at load time, never a literal value in these files -
see `infra/app_config.py`'s docstring for the substitution syntax.
Every file has a committed `.example` twin with the same shape.

`config_hosts.json` and `config_email.json` are gitignored by exact path
even though this folder is otherwise committed - they carry this
deployment's real host list and approver addresses. `config_extensions.json`
and `config_capabilities.json` are ordinary committed files.
```

- [ ] **Step 3: `mcp_server/src/secrets/README.md`**

```markdown
# src/secrets/

The actual credential values that `../configs/*.json` refers to by name
via `${VAR}` placeholders (e.g. `"password": "${SMTP_PASSWORD}"`).
Gitignored entirely except for the `.example` files and this README -
copy each `*.env.example` to the matching `*.env` and fill in real
values.

- **`secret_app.env`** - `MCP_HOST`, `MCP_PORT`, `MCP_PUBLIC_BASE_URL`.
  Not secrets in the "must never leak" sense, but deployment-specific and
  kept alongside the ones that are, same as `config_extensions.json`
  living next to `config_capabilities.json`.
- **`secret_smtp.env`** - `SMTP_PASSWORD`, backing `config_email.json`'s
  `"password"`.
- **`secret_ssh.env`** - `SSH_HOST_KEY_POLICY`, `SSH_KNOWN_HOSTS`, and one
  `*_SSH_PASSWORD` variable per password-authenticated entry in
  `config_hosts.json`.

All three are loaded by `run.py` before anything else (every `.env` file
in this folder, not a fixed list of names - a future capability that
needs its own secret adds a file here with no changes to `run.py`).

In production, prefer having the service manager, container runtime, or
a secrets manager put these variables in the environment directly
instead of a file on disk - nothing else has to change for that to work.
```

- [ ] **Step 4: `mcp_server/src/data/README.md`**

```markdown
# src/data/

Runtime state shared across capabilities - not tied to any single one,
so it doesn't live inside a `capabilities/<name>/` folder. Gitignored
except for this README.

- **`pending_requests.db`** - `infra/pending_requests.py`'s SQLite store
  for approval-gated / resumable requests (`infra/approvals.py`). Any
  capability that registers a `GatedCapability` uses this same file;
  none of them own it individually.

A capability that owns runtime state outright - state nothing else ever
reads or writes - keeps it in its own `capabilities/<name>/data/`
instead. `capabilities/otp/README.md` is the example: `otp.db` is
created there, not here, because only the `otp` capability ever touches
it.
```

- [ ] **Step 5: `mcp_server/src/mcp_server/capabilities/host_health/README.md`**

```markdown
# capabilities/host_health/

CPU, memory, disk, and uptime for a configured SSH host - exposed both
as a tool (`get_host_health_tool`, for a model) and a resource
(`host://health/{name}`, for a client reading a URI directly). Same
domain logic underneath (`resources/host_health/domain.py`); this
folder's `tool.py` wraps it for the model-facing case.

**Reads:** `../../../configs/config_hosts.json` (the host inventory) and,
through `infra/ssh.py`, `../../../secrets/secret_ssh.env` (host-key
policy and any password-authenticated host's `*_SSH_PASSWORD`).

**Owns no data or secrets of its own** - it only reads, over SSH, and
returns a report; nothing it produces is persisted.

**Toggle:** `"host_health"` in `../../../configs/config_capabilities.json`.
Disabling it removes both the tool and the resource.
```

- [ ] **Step 6: `mcp_server/src/mcp_server/capabilities/otp/README.md`**

```markdown
# capabilities/otp/

Emails a one-time passcode to a configured address and verifies it back
- `request_otp_tool` / `verify_otp_tool`. The code is never returned to
the caller; only whoever reads the inbox can complete the check. See
`domain.py`'s docstring for why that's the entire point of the
mechanism.

**Reads:** `../../../configs/config_email.json` (recipient allowlist,
domains, SMTP settings) and, through `infra/email.py`,
`../../../secrets/secret_smtp.env` (`SMTP_PASSWORD`) - both shared with
`infra/approvals.py`, not owned by this capability alone.

**Owns:** `data/otp.db` - `infra/otp.py`'s salted-hash store of issued
codes. Created automatically on first use; nothing else reads or writes
it (contrast `../../../data/README.md`'s `pending_requests.db`, which
several capabilities could share). Not committed - regenerable, and
holds nothing worth keeping between runs (codes expire in minutes).

**Toggle:** `"otp"` in `../../../configs/config_capabilities.json`.
```

- [ ] **Step 7: Update `capabilities/__init__.py`'s "Add a new capability" list**

Change:

```python
Add a new capability by:
  1. mkdir capabilities/<name>/ with an __init__.py
  2. capabilities/<name>/contract.py
  3. capabilities/<name>/domain.py
  4. capabilities/<name>/tool.py
  5. Add `from mcp_server.capabilities.<name> import tool` to run.py
```

to:

```python
Add a new capability by:
  1. mkdir capabilities/<name>/ with an __init__.py
  2. capabilities/<name>/contract.py
  3. capabilities/<name>/domain.py
  4. capabilities/<name>/tool.py
  5. capabilities/<name>/README.md - what it reads, what (if anything)
     it owns under its own data/ or secrets/, how to toggle it off
  6. Add a toggle entry to ../configs/config_capabilities.json and
     config_capabilities.json.example
  7. Gate `from mcp_server.capabilities.<name> import tool` behind
     `capability_enabled(...)` in run.py, following host_health/otp
```

- [ ] **Step 8: Commit**

```bash
git add mcp_server/README.md mcp_server/src/configs/README.md mcp_server/src/secrets/README.md \
        mcp_server/src/data/README.md \
        mcp_server/src/mcp_server/capabilities/host_health/README.md \
        mcp_server/src/mcp_server/capabilities/otp/README.md \
        mcp_server/src/mcp_server/capabilities/__init__.py
git commit -m "docs: add README to mcp_server root and every src/ and capability folder"
```

---

## Task 8: Update `zima_host.yaml` for the new layout

**Files:**
- Modify: `mcp_server/zima_host.yaml`

**Interfaces:** none - deployment doc only.

- [ ] **Step 1: Drop the now-default-correct environment overrides**

Since `working_dir: /app` and every new default (`src/configs`, `src/data/pending_requests.db`,
`src/mcp_server/capabilities/otp/data/otp.db`, `src/logs`) is already
`/app`-relative, `CONFIG_PATH`, `PENDING_REQUESTS_PATH`, `OTP_PATH`, and
`MCP_LOG_DIR` no longer need to be set at all. Change the `environment:`
block from:

```yaml
    environment:
      # MCP_HOST must be 0.0.0.0, not the .env.example default of
      # 127.0.0.1 - "loopback" means loopback INSIDE this container,
      # which the `ports:` mapping above can never reach from outside.
      #
      # This server has NO authentication of its own (see its own
      # startup banner's WARNING line about this) - anything that can
      # reach port 8010 can run every registered tool with arguments of
      # its choosing. Binding 0.0.0.0 is what makes the port mapping
      # work at all, so restrict who can reach it at the NETWORK level
      # instead (NAS firewall rule / VLAN / don't forward this port
      # past your LAN) - nothing at the app level will.
      - MCP_HOST=0.0.0.0
      - MCP_PORT=8010
      - CONFIG_PATH=/app/config.json
      - MCP_LOG_DIR=/app/logs
      - PENDING_REQUESTS_PATH=/app/pending_requests.db
      - OTP_PATH=/app/otp.db
      # Only matters for approval-gated capabilities (an emailed
      # approve/deny link) - point it at whatever address actually
      # resolves back to this container from wherever you'll be reading
      # that email (your NAS's LAN IP or a hostname, not 127.0.0.1).
      - MCP_PUBLIC_BASE_URL=http://[YOUR NAS LAN IP OR HOSTNAME]:8010
      # "reject" (default) needs a real known_hosts file with your SSH
      # hosts' keys already in it - mount or create one at this path, or
      # switch to "auto" to trust-on-first-use instead.
      - SSH_HOST_KEY_POLICY=reject
      - SSH_KNOWN_HOSTS=/app/known_hosts
      # Only needed if config.json actually references ${SMTP_PASSWORD}
      # / ${DESKTOP_SSH_PASSWORD} - delete whichever line you don't use,
      # a ${VAR} that resolves to empty fails startup on purpose (see
      # .env.example).
      - SMTP_PASSWORD=[PLACE YOUR SMTP APP PASSWORD HERE]
      - DESKTOP_SSH_PASSWORD=[PLACE YOUR SSH PASSWORD HERE]
```

to:

```yaml
    environment:
      # MCP_HOST must be 0.0.0.0, not secret_app.env.example's default of
      # 127.0.0.1 - "loopback" means loopback INSIDE this container,
      # which the `ports:` mapping above can never reach from outside.
      #
      # This server has NO authentication of its own (see its own
      # startup banner's WARNING line about this) - anything that can
      # reach port 8010 can run every registered tool with arguments of
      # its choosing. Binding 0.0.0.0 is what makes the port mapping
      # work at all, so restrict who can reach it at the NETWORK level
      # instead (NAS firewall rule / VLAN / don't forward this port
      # past your LAN) - nothing at the app level will.
      - MCP_HOST=0.0.0.0
      - MCP_PORT=8010
      # Every other path setting (config files under src/configs/,
      # pending_requests.db and otp.db under src/data/ and
      # src/mcp_server/capabilities/otp/data/, logs under src/logs/)
      # already defaults to a path relative to the working directory,
      # which is /app here - so none of them need overriding as long as
      # this folder's whole contents (including src/) were copied in, as
      # step 1 above says.
      #
      # Only matters for approval-gated capabilities (an emailed
      # approve/deny link) - point it at whatever address actually
      # resolves back to this container from wherever you'll be reading
      # that email (your NAS's LAN IP or a hostname, not 127.0.0.1).
      - MCP_PUBLIC_BASE_URL=http://[YOUR NAS LAN IP OR HOSTNAME]:8010
      # "reject" (default) needs a real known_hosts file with your SSH
      # hosts' keys already in it - mount or create one at this path, or
      # switch to "auto" to trust-on-first-use instead.
      - SSH_HOST_KEY_POLICY=reject
      - SSH_KNOWN_HOSTS=/app/known_hosts
      # Only needed if config_email.json / config_hosts.json actually
      # reference ${SMTP_PASSWORD} / ${DESKTOP_SSH_PASSWORD} - delete
      # whichever line you don't use, a ${VAR} that resolves to empty
      # fails startup on purpose (see secret_smtp.env.example /
      # secret_ssh.env.example).
      - SMTP_PASSWORD=[PLACE YOUR SMTP APP PASSWORD HERE]
      - DESKTOP_SSH_PASSWORD=[PLACE YOUR SSH PASSWORD HERE]
```

- [ ] **Step 2: Commit**

```bash
git add mcp_server/zima_host.yaml
git commit -m "docs: update zima_host.yaml for the src/configs + src/secrets + src/data layout"
```

---

## Final check

- [ ] Run `cd mcp_server && pytest -v` one more time - full suite green.
- [ ] Run `cd "D:\User\Documents\Programming\Python\MCPServer" && git status` - confirm nothing unexpected is staged or untracked (the real `config_hosts.json`/`config_email.json`/`secret_*.env` files should show as ignored, not untracked).
- [ ] Manually start the server (`run_mcp_server.bat`) one final time and confirm the banner looks right with both capabilities enabled - this is the user's own manual verification step.
