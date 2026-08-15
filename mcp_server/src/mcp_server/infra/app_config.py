"""Loader for the JSON config file that holds per-deployment settings.

Three different kinds of configuration live in this project, deliberately
kept apart:

  - ``mcp_server/config.py`` - process settings read from environment
    variables (bind host/port, where this file lives). Small, flat,
    always present.
  - this file - structured, per-deployment data read from the JSON file
    at ``settings.config_path``: host inventories, ports, addresses,
    recipient lists. Too nested to be comfortable as env vars.
  - the environment - the actual secret *values*, which the JSON file
    only refers to by name (see below).

Structure and secrets want opposite treatment. Structure benefits from
being versioned, diffed and reviewed; secrets should never be written
down next to it. Mixing both into one file is what makes a config file
feel radioactive - you can't share it, commit it, or paste it into an
issue without leaking something.

So a string anywhere in the config file may contain ``${VAR}``, which is
replaced with that environment variable's value::

    "password": "${SMTP_PASSWORD}"

That keeps ``config.json`` free of secrets - it names them instead of
holding them - while the values live wherever is appropriate for the
deployment: ``.env`` in development, or injected by the service manager,
container runtime, or a secrets manager in production. Swapping that
backend later means changing how the environment gets populated, not
this file's format and not any domain code.

Write ``$$`` for a literal ``$`` if a value genuinely needs to contain
``${...}`` text rather than have it substituted.

Substitution is *per section*, not per file: ``load_config`` parses and
returns the document untouched, and each loader calls ``resolve_section``
on just the subtree it is about to read. Resolving the whole document up
front was the obvious implementation and it was wrong - one unset SSH
password under ``hosts`` made ``load_email_config`` raise, so a machine
nobody was talking to could stop mail from going out. A deployment is
allowed to have half its secrets present; only the half it actually uses
has to be.

Deliberately fails loudly, at load time, with a message naming the file
and the exact key - rather than returning ``{}`` or an empty string and
letting a capability fail much later with a confusing error deep inside
domain logic. The rule for which exception: ``KeyError`` when something
required is absent (a config key, an environment variable), ``ValueError``
when it's present but unusable (malformed JSON, an empty secret).

Add a loader function per config section as capabilities need them,
following ``load_email_config`` below: read the section, resolve it with
``resolve_section``, validate what's required, return a frozen dataclass. Domain code should take that
dataclass, never a raw dict - that way a typo in config.json is caught
here instead of at the call site.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ${NAME}, where NAME is a normal environment-variable identifier. A "$"
# not followed by "{" is left alone, so ordinary text and anything shell-
# flavored ("$HOME", "US$5") passes through untouched.
#
# "$$" is an escape for a literal "$", so "$${NAME}" survives as the text
# "${NAME}" instead of being looked up (same convention as
# docker-compose). Without it there'd be no way to store a string that
# genuinely contains ${...} - which is easy to hit by accident, e.g. a
# template or a comment describing this very syntax.
_ENV_PLACEHOLDER = re.compile(r"\$\$|\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class EmailConfig:
    smtp_server: str
    smtp_port: int
    from_address: str
    # The standing recipient list, and empty is a real configuration: a
    # deployment that only mails one-time codes to addresses the caller
    # names (see `allowed_recipient_domains`) has nobody standing behind
    # it. `send_email` refuses an empty final recipient list at send time,
    # which is the moment it actually matters.
    to: list[str] = field(default_factory=list)
    # Empty means "connect and send without authenticating". That's not a
    # degraded fallback, it's how LAN relays and local MTAs normally work -
    # they authorize by source address, and offering AUTH to them makes the
    # send fail outright. A consumer provider will simply reject the mail
    # instead, which is the correct outcome for a missing password.
    password: str = ""
    # How the connection is protected: "starttls" | "ssl" | "none".
    # Defaults to STARTTLS, which is what this module did before the field
    # existed; `load_email_config` infers a better default from the port.
    security: str = "starttls"
    # Who receives approval requests for gated capabilities. Kept separate
    # from `to` on purpose: general notifications and "press this button
    # to let something irreversible happen" are different audiences, and
    # the second one is a standing authorization list. Defaults to `to`
    # when unset, so the split is available without being mandatory.
    approver_emails: list[str] = field(default_factory=list)
    # Domains that a caller may name any address at - used by the OTP
    # capability, which otherwise only sends to the exact addresses above.
    # Empty is the default and means "no domains", never "any domain":
    # widening an allowlist because a key is absent is the one failure mode
    # here that nobody would notice, so the absent case is the strict one.
    allowed_recipient_domains: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HostConfig:
    """One machine this server can reach over SSH.

    ``os`` is declared rather than detected. Detection would cost a round
    trip on every call and can only ever be a guess from command output,
    while the answer is a stable fact about a machine you own - so it
    belongs in config, where getting it wrong is visible and fixable.
    It decides which command set the domain code uses, and Linux and
    Windows share almost none.
    """

    name: str
    hostname: str
    user: str
    os: str  # "linux" | "windows"
    port: int = 22
    key: str | None = None
    password: str | None = None


@dataclass(frozen=True)
class ExtensionConfig:
    """One other MCP server this server connects out to as a client and
    re-exposes as its own namespaced tools (see ``infra/extensions.py``).

    Two transports, chosen by which of ``command``/``url`` the config
    entry supplies (see ``_build_extension``):

    - ``transport="stdio"`` - this server spawns the upstream as a local
      subprocess. ``command``/``args`` are exactly what
      ``StdioServerParameters`` wants - kept as plain strings here rather
      than parsed further, since the right shape for "how do I launch
      this process" is whatever the upstream server's own README says to
      run.
    - ``transport="http"`` - the upstream is already running somewhere
      and this server connects to it as a client over streamable HTTP,
      the same way ``chat_app/src/chat_app/services/mcp_client.py``
      already talks to *this* server. ``url`` is that server's MCP
      endpoint.

    ``command`` and ``url`` both default to their transport's "unused"
    value (``""`` / ``None``) rather than being made fully optional
    without a default, so a config built directly (as
    ``extension_routes.py``'s POST handler does) only has to supply the
    fields its transport actually uses.
    """

    id: str
    label: str
    description: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    transport: str = "stdio"
    url: str | None = None


def _resolve_placeholder(name: str, *, where: str, config_path: Path) -> str:
    value = os.environ.get(name)
    if value is None:
        raise KeyError(
            f"Config file {config_path} refers to ${{{name}}} at '{where}', but "
            f"{name} is not set in the environment. Add it to mcp_server/.env "
            f"(or however this deployment supplies secrets)."
        )
    if value == "":
        # Almost always "SMTP_PASSWORD=" left blank in .env rather than a
        # genuinely empty secret - and a blank password fails later at
        # SMTP login with a far less obvious message. Write "" directly in
        # config.json if an empty value is really what you want.
        raise ValueError(
            f"Config file {config_path} refers to ${{{name}}} at '{where}', but "
            f"{name} is set to an empty string. Give it a value, or put a "
            f"literal \"\" in the config file if empty is intended."
        )
    return value


def resolve_section(value: Any, *, where: str, config_path: Path) -> Any:
    """Substitute ${VAR} inside every string of one subtree of the config.

    ``where`` is that subtree's *full* dotted path from the top of the
    document ("email", "hosts.desktop"), not a name local to it, and it is
    extended as the walk descends. Callers resolve a slice but errors still
    read ``hosts.desktop.password`` - the operator has to open config.json
    and find the line, and a path relative to whatever the loader happened
    to pass in would send them looking in the wrong place. Pass ``""`` for
    a whole document.

    Recurses through dicts and lists so any section added later gets this
    for free. Only values are touched, never keys - a computed key name
    would make the config unreadable for no benefit. Non-string scalars
    (ints, bools, null) pass through untouched.
    """
    if isinstance(value, dict):
        return {
            key: resolve_section(item, where=f"{where}.{key}" if where else str(key), config_path=config_path)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            resolve_section(item, where=f"{where}[{index}]", config_path=config_path)
            for index, item in enumerate(value)
        ]
    if isinstance(value, str):
        def substitute(match: re.Match[str]) -> str:
            if match.group(0) == "$$":
                return "$"
            return _resolve_placeholder(match.group(1), where=where, config_path=config_path)

        return _ENV_PLACEHOLDER.sub(substitute, value)
    return value


def load_config(config_path: Path) -> dict[str, Any]:
    """Read and parse the config file. Raises on anything unusable.

    Returns the document exactly as written, ``${VAR}`` placeholders and
    all; a loader resolves the part it needs with ``resolve_section``.
    """
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}. Copy config.json.example "
            f"and point CONFIG_PATH at it."
        )
    try:
        with config_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as error:
        raise ValueError(f"Config file {config_path} is not valid JSON: {error}") from error

    if not isinstance(data, dict):
        raise ValueError(f"Config file {config_path} must contain a JSON object at the top level")
    return data


def _require(section: dict[str, Any], key: str, *, section_name: str, config_path: Path) -> Any:
    if key not in section:
        raise KeyError(f"Config file {config_path} is missing '{section_name}.{key}'")
    return section[key]


def normalize_recipient_domain(value: str) -> str:
    """One ``email.allowed_recipient_domains`` entry, in comparison form.

    Public, and imported by ``capabilities/otp/domain.py`` rather than
    reimplemented there, because two spellings of "normalized" is how an
    allowlist quietly stops matching what the operator wrote - and an
    ``EmailConfig`` can be built directly, in a test or a hand-written
    setup, without ever passing through this loader. Both sides calling
    the same function is what makes that safe.

    A leading ``@`` or ``.`` is stripped rather than rejected: asked for a
    domain, people write ``@example.com`` or ``.example.com`` about as
    often as the bare form, and all three plainly mean the same thing.
    Nothing else is repaired - this is not an address parser, and a value
    that isn't a domain just fails to match anything, which is the
    direction a mistake here should fail in.
    """
    return value.strip().lower().lstrip("@.")


SUPPORTED_EMAIL_SECURITY = ("starttls", "ssl", "none")

# The IANA-registered port for implicit-TLS message submission. Gmail,
# Outlook, Yahoo, iCloud and every mainstream host use it for exactly that,
# so seeing it in the config is enough to know the transport - which is why
# `security` can be inferred rather than demanded from every deployment.
IMPLICIT_TLS_PORT = 465


def load_email_config(config_path: Path) -> EmailConfig:
    """Parse the "email" section into an EmailConfig.

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
    config = load_config(config_path)
    section = config.get("email")
    if not isinstance(section, dict):
        raise KeyError(f"Config file {config_path} is missing an 'email' section")
    # Only this section: an unset ${DESKTOP_SSH_PASSWORD} under `hosts`
    # has nothing to do with sending mail and must not stop it.
    section = resolve_section(section, where="email", config_path=config_path)

    def required(key: str) -> Any:
        return _require(section, key, section_name="email", config_path=config_path)

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
            f"Config file {config_path}: 'email.security' is {security!r}, "
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


SUPPORTED_HOST_OS = ("linux", "windows")


def _hosts_section(config_path: Path) -> dict[str, Any]:
    """The raw "hosts" mapping, placeholders still unresolved."""
    config = load_config(config_path)
    section = config.get("hosts")
    if not isinstance(section, dict):
        raise KeyError(f"Config file {config_path} is missing a 'hosts' section")
    return section


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
        raise ValueError(f"Config file {config_path}: 'hosts.{name}' must be an object")

    # Resolved under the entry's full path, so the message still reads
    # 'hosts.desktop.password' and points at a findable line.
    entry = resolve_section(entry, where=f"hosts.{name}", config_path=config_path)

    def required(key: str) -> Any:
        return _require(entry, key, section_name=f"hosts.{name}", config_path=config_path)

    host_os = str(required("os")).strip().lower()
    if host_os not in SUPPORTED_HOST_OS:
        raise ValueError(
            f"Config file {config_path}: 'hosts.{name}.os' is {host_os!r}, "
            f"expected one of {', '.join(SUPPORTED_HOST_OS)}."
        )

    key = entry.get("key")
    password = entry.get("password")
    if not key and not password:
        # Failing here beats failing at connect time, where it surfaces
        # as a generic auth error and looks like a wrong password.
        raise KeyError(
            f"Config file {config_path}: 'hosts.{name}' needs a 'key' or a 'password'."
        )

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
    """Parse the "hosts" section into HostConfigs keyed by name.

    This one really does need every host's secrets present, because it
    claims to return every host - a caller listing the inventory would
    otherwise get a silently short list. Reach for ``load_host_config``
    when you only want one; that is the call that survives a broken
    sibling.
    """
    section = _hosts_section(config_path)
    return {
        name: _build_host(name, entry, config_path=config_path)
        for name, entry in section.items()
    }


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


# --- extensions ----------------------------------------------------------
# Mirrors the "hosts" loaders immediately above: per-entry resolution, and
# a broken sibling can't take down the others. One deliberate difference -
# see _extensions_section below.


def _extensions_section(config_path: Path) -> dict[str, Any]:
    """The raw "extensions" mapping, placeholders still unresolved.

    Unlike ``_hosts_section``, an entirely absent key returns ``{}``
    instead of raising. ``load_hosts_config``/``load_host_config`` are
    only ever called lazily, when some tool call actually needs a host,
    so a deployment that never touches SSH never has to satisfy "hosts".
    Extensions are different: ``infra/extensions.py`` calls
    ``load_extensions_config`` unconditionally on every startup, before a
    single tool has been requested. Raising on an absent section would
    mean every config.json written before this feature existed - which
    is all of them - fails to start the moment this ships. Absent has to
    mean "none configured", not "config is broken"; a section that IS
    present but malformed still raises, same as everywhere else in this
    module.
    """
    config = load_config(config_path)
    section = config.get("extensions", {})
    if not isinstance(section, dict):
        raise ValueError(f"Config file {config_path}: 'extensions' must be an object")
    return section


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
        raise ValueError(f"Config file {config_path}: 'extensions.{id_}' must be an object")

    entry = resolve_section(entry, where=f"extensions.{id_}", config_path=config_path)

    def required(key: str) -> Any:
        return _require(entry, key, section_name=f"extensions.{id_}", config_path=config_path)

    has_command = "command" in entry
    has_url = "url" in entry
    if has_command and has_url:
        raise ValueError(
            f"Config file {config_path}: 'extensions.{id_}' has both 'command' and 'url' - "
            f"a stdio extension (spawned as a subprocess) uses 'command' and optionally "
            f"'args'; an http extension (already running elsewhere) uses 'url'. Remove one."
        )
    if not has_command and not has_url:
        raise ValueError(
            f"Config file {config_path}: 'extensions.{id_}' needs either 'command' (to launch "
            f"a stdio extension) or 'url' (to connect to an already-running http extension)."
        )

    label = str(required("label"))
    description = str(entry.get("description", ""))

    if has_url:
        url = str(required("url")).strip()
        if not url:
            raise ValueError(f"Config file {config_path}: 'extensions.{id_}.url' must not be empty")
        return ExtensionConfig(
            id=id_,
            label=label,
            description=description,
            transport="http",
            url=url,
        )

    args = entry.get("args", [])
    if not isinstance(args, list):
        raise ValueError(f"Config file {config_path}: 'extensions.{id_}.args' must be a list")

    return ExtensionConfig(
        id=id_,
        label=label,
        description=description,
        transport="stdio",
        command=str(required("command")),
        args=[str(item) for item in args],
    )


def load_extensions_config(config_path: Path) -> dict[str, ExtensionConfig]:
    """Parse the "extensions" section into ExtensionConfigs keyed by id.

    Called once at startup for the full set - see the note on
    ``_extensions_section`` for why a missing section is empty rather than
    an error, and ``_build_extension`` for why one broken entry doesn't
    stop the rest from loading.
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
    """Insert or overwrite one entry under config.json's "extensions"
    section, leaving every other section and entry untouched.

    Reads with ``load_config`` (not a loader that resolves placeholders),
    so an unrelated ``${VAR}`` elsewhere in the file - in ``email`` or
    another extension's ``args`` - passes through byte-for-byte instead
    of being baked in as its resolved value. ``config`` itself is
    expected to already hold whatever it wants written literally (this
    is the shape ``infra/extensions.py``'s runtime ``add_extension``
    passes straight from an HTTP request body, which never contains
    ``${VAR}`` placeholders to begin with).

    Written by transport: a stdio config's ``command``/``args`` for an
    http config, and just ``url``, so a re-read through
    ``load_extensions_config`` gets exactly what ``_build_extension``
    expects for that transport - no leftover empty ``command``/``url``
    from the other branch's field defaults.
    """
    data = load_config(config_path)
    section = data.setdefault("extensions", {})

    entry: dict[str, Any] = {"label": config.label, "description": config.description}
    if config.transport == "http":
        entry["url"] = config.url
    else:
        entry["command"] = config.command
        entry["args"] = config.args
    section[config.id] = entry

    _write_config(config_path, data)


def delete_extension_config(config_path: Path, extension_id: str) -> None:
    """Remove one entry from config.json's "extensions" section.

    Idempotent - removing an id that's already absent (or an entirely
    absent "extensions" section) is not an error, since the caller's
    goal ("this id must not be in config.json") is already true.
    """
    data = load_config(config_path)
    section = data.setdefault("extensions", {})
    section.pop(extension_id, None)
    _write_config(config_path, data)
