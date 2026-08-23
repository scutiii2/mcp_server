"""Tests for infra/app_config.py.

The point of this module is that it fails loudly, so most of these assert
on the *error*, not the happy path - a config loader that returns ``{}``
on a missing file is exactly what this project avoids.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.infra.app_config import (
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
        "args": ["-m", "src._fixtures.reference_extension_server"],
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
    assert extensions["reference"].args == ["-m", "src._fixtures.reference_extension_server"]


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
        args=["-m", "src._fixtures.reference_extension_server"],
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
