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
    load_config,
    load_email_config,
    load_host_config,
    load_hosts_config,
)


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


VALID_EMAIL = {
    "smtp_server": "smtp.example.com",
    "smtp_port": 587,
    "from": "notifications@example.com",
    "password": "changeme",
    "to": ["team@example.com"],
}


# --- ${VAR} resolution -------------------------------------------------
# The point of this feature is that config.json names secrets instead of
# holding them, so these cover both halves: the value arriving correctly,
# and a clear failure when the environment doesn't supply it.


def test_placeholder_is_replaced_with_the_environment_value(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "s3cret")
    path = _write(tmp_path, {"email": {**VALID_EMAIL, "password": "${SMTP_PASSWORD}"}})

    assert load_email_config(path).password == "s3cret"


def test_placeholder_can_be_embedded_in_a_larger_string(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MAIL_HOST", "mail.internal")
    path = _write(tmp_path, {"email": {**VALID_EMAIL, "smtp_server": "smtp.${MAIL_HOST}.example"}})

    assert load_email_config(path).smtp_server == "smtp.mail.internal.example"


def test_placeholders_resolve_inside_lists(tmp_path: Path, monkeypatch):
    """Resolution walks the whole structure, so a section added later gets
    it without touching this module."""
    monkeypatch.setenv("ONCALL_EMAIL", "oncall@example.com")
    path = _write(tmp_path, {"email": {**VALID_EMAIL, "to": ["team@example.com", "${ONCALL_EMAIL}"]}})

    assert load_email_config(path).to == ["team@example.com", "oncall@example.com"]


def test_unset_variable_raises_naming_both_the_variable_and_the_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    path = _write(tmp_path, {"email": {**VALID_EMAIL, "password": "${SMTP_PASSWORD}"}})

    with pytest.raises(KeyError) as error:
        load_config(path)

    message = str(error.value)
    assert "SMTP_PASSWORD" in message
    assert "email.password" in message  # the JSON path, so you know where to look


def test_empty_variable_raises_rather_than_yielding_a_blank_secret(tmp_path: Path, monkeypatch):
    """An unset var and a blank one are the same mistake in practice
    ("SMTP_PASSWORD=" in .env); failing here beats a confusing SMTP
    login error later."""
    monkeypatch.setenv("SMTP_PASSWORD", "")
    path = _write(tmp_path, {"email": {**VALID_EMAIL, "password": "${SMTP_PASSWORD}"}})

    with pytest.raises(ValueError, match="empty string"):
        load_config(path)


def test_literal_empty_string_is_still_allowed(tmp_path: Path):
    """The documented escape hatch: write "" directly if empty is intended."""
    path = _write(tmp_path, {"email": {**VALID_EMAIL, "password": ""}})

    assert load_email_config(path).password == ""


def test_non_string_values_pass_through_untouched(tmp_path: Path):
    path = _write(tmp_path, {"email": VALID_EMAIL, "extras": {"count": 3, "on": True, "nothing": None}})

    assert load_config(path)["extras"] == {"count": 3, "on": True, "nothing": None}


def test_bare_dollar_signs_are_not_treated_as_placeholders(tmp_path: Path):
    """Only ${NAME} interpolates - a lone "$" is ordinary text, so shell-ish
    or currency strings survive intact."""
    path = _write(tmp_path, {"email": VALID_EMAIL, "note": "costs US$5, not $HOME"})

    assert load_config(path)["note"] == "costs US$5, not $HOME"


def test_double_dollar_escapes_a_literal_placeholder(tmp_path: Path, monkeypatch):
    """Without an escape there'd be no way to store text that genuinely
    contains ${...} - which is easy to hit by accident (this project's own
    config.json.example did, in a comment describing the syntax)."""
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    path = _write(tmp_path, {"email": VALID_EMAIL, "note": "write $${SMTP_PASSWORD} to refer to it"})

    assert load_config(path)["note"] == "write ${SMTP_PASSWORD} to refer to it"


def test_double_dollar_outside_a_placeholder_becomes_one_dollar(tmp_path: Path):
    path = _write(tmp_path, {"email": VALID_EMAIL, "note": "costs 5$$"})

    assert load_config(path)["note"] == "costs 5$"


def test_placeholder_value_is_not_itself_expanded(tmp_path: Path, monkeypatch):
    """No recursive expansion: whatever the environment holds is used
    literally, so a value that happens to contain ${...} can't trigger
    another lookup."""
    monkeypatch.setenv("WEIRD", "${NOT_A_VAR}")
    monkeypatch.delenv("NOT_A_VAR", raising=False)
    path = _write(tmp_path, {"email": VALID_EMAIL, "note": "${WEIRD}"})

    assert load_config(path)["note"] == "${NOT_A_VAR}"


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
    path = _write(tmp_path, {"email": VALID_EMAIL})

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
    path = _write(tmp_path, {"email": VALID_EMAIL})

    assert load_email_config(path).approver_emails == ["team@example.com"]


def test_approver_emails_override_the_general_recipients(tmp_path: Path):
    """When set, approvers are a *different* list, not an addition to it -
    an approval link is authority to run something irreversible, and
    everyone on the general notification list shouldn't inherit that."""
    path = _write(tmp_path, {"email": {**VALID_EMAIL, "approver_emails": ["boss@example.com"]}})

    config = load_email_config(path)

    assert config.approver_emails == ["boss@example.com"]
    assert config.to == ["team@example.com"]


def test_missing_email_section_raises(tmp_path: Path):
    path = _write(tmp_path, {"something_else": {}})
    with pytest.raises(KeyError, match="email"):
        load_email_config(path)


def test_missing_required_key_names_the_key(tmp_path: Path):
    incomplete = {k: v for k, v in VALID_EMAIL.items() if k != "smtp_server"}
    path = _write(tmp_path, {"email": incomplete})
    with pytest.raises(KeyError, match="email.smtp_server"):
        load_email_config(path)


def test_password_may_be_omitted_entirely(tmp_path: Path):
    """An unauthenticated send is a real configuration - a LAN relay that
    authorizes by source address - not an oversight. Demanding the key
    would force a dummy value that then gets offered to a server with no
    AUTH extension, which fails the send."""
    no_password = {k: v for k, v in VALID_EMAIL.items() if k != "password"}
    path = _write(tmp_path, {"email": no_password})

    assert load_email_config(path).password == ""


def test_security_defaults_to_starttls_on_a_submission_port(tmp_path: Path):
    path = _write(tmp_path, {"email": VALID_EMAIL})

    assert load_email_config(path).security == "starttls"


def test_port_465_infers_implicit_tls(tmp_path: Path):
    """465 is the registered implicit-TLS submission port and every
    mainstream provider uses it as such, so the port is enough to know the
    transport - saving a field that would otherwise be wrong-by-default
    for the most common consumer setup."""
    path = _write(tmp_path, {"email": {**VALID_EMAIL, "smtp_port": 465}})

    assert load_email_config(path).security == "ssl"


def test_explicit_security_beats_the_port_inference(tmp_path: Path):
    """Inference is a convenience, not a rule: a relay can listen for
    STARTTLS on 465, and the config file has to win when it disagrees."""
    path = _write(tmp_path, {"email": {**VALID_EMAIL, "smtp_port": 465, "security": "starttls"}})

    assert load_email_config(path).security == "starttls"


def test_security_is_normalized(tmp_path: Path):
    path = _write(tmp_path, {"email": {**VALID_EMAIL, "security": " SSL "}})

    assert load_email_config(path).security == "ssl"


def test_unsupported_security_is_rejected_rather_than_falling_back(tmp_path: Path):
    """A typo must not quietly become a plaintext connection: the password
    would go out in the clear and nothing in the run would say so."""
    path = _write(tmp_path, {"email": {**VALID_EMAIL, "security": "tls"}})

    with pytest.raises(ValueError, match="expected one of"):
        load_email_config(path)


def test_single_recipient_string_is_accepted_as_a_list(tmp_path: Path):
    """A bare string is the obvious thing to write for one recipient, and
    silently iterating it character-by-character would be a nasty way to
    find out otherwise."""
    path = _write(tmp_path, {"email": {**VALID_EMAIL, "to": "solo@example.com"}})

    assert load_email_config(path).to == ["solo@example.com"]


def test_string_port_is_coerced_to_int(tmp_path: Path):
    path = _write(tmp_path, {"email": {**VALID_EMAIL, "smtp_port": "587"}})

    assert load_email_config(path).smtp_port == 587


# --- hosts -------------------------------------------------------------

VALID_HOSTS = {
    "zima": {"hostname": "192.168.1.10", "user": "root", "os": "linux", "key": "/root/.ssh/id"},
    "desktop": {"hostname": "192.168.1.20", "user": "User", "os": "windows", "password": "pw"},
}


def test_hosts_are_keyed_by_name(tmp_path: Path):
    path = _write(tmp_path, {"hosts": VALID_HOSTS})

    hosts = load_hosts_config(path)

    assert set(hosts) == {"zima", "desktop"}
    assert hosts["zima"].name == "zima"
    assert hosts["desktop"].os == "windows"


def test_port_defaults_to_22(tmp_path: Path):
    path = _write(tmp_path, {"hosts": VALID_HOSTS})

    assert load_hosts_config(path)["zima"].port == 22


def test_os_is_normalized(tmp_path: Path):
    path = _write(tmp_path, {"hosts": {"a": {**VALID_HOSTS["zima"], "os": "  Linux "}}})

    assert load_hosts_config(path)["a"].os == "linux"


def test_unsupported_os_is_rejected(tmp_path: Path):
    """The OS picks the entire command set, so a typo would otherwise
    surface as a pile of 'command not found'."""
    path = _write(tmp_path, {"hosts": {"a": {**VALID_HOSTS["zima"], "os": "darwin"}}})

    with pytest.raises(ValueError, match="expected one of"):
        load_hosts_config(path)


def test_host_without_key_or_password_is_rejected(tmp_path: Path):
    """Failing here beats failing at connect time, where it looks like a
    wrong password rather than a missing one."""
    path = _write(tmp_path, {"hosts": {"a": {"hostname": "h", "user": "u", "os": "linux"}}})

    with pytest.raises(KeyError, match="needs a 'key' or a 'password'"):
        load_hosts_config(path)


def test_host_secrets_resolve_from_the_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DESKTOP_SSH_PASSWORD", "hunter2")
    path = _write(tmp_path, {"hosts": {"a": {**VALID_HOSTS["desktop"], "password": "${DESKTOP_SSH_PASSWORD}"}}})

    assert load_hosts_config(path)["a"].password == "hunter2"


def test_unknown_host_names_the_ones_that_exist(tmp_path: Path):
    """The caller is usually a model that guessed a name; the fix is
    knowing what it could have said."""
    path = _write(tmp_path, {"hosts": VALID_HOSTS})

    with pytest.raises(KeyError, match="desktop, zima"):
        load_host_config(path, "nas")


def test_missing_hosts_section_raises(tmp_path: Path):
    path = _write(tmp_path, {"email": VALID_EMAIL})

    with pytest.raises(KeyError, match="hosts"):
        load_hosts_config(path)
