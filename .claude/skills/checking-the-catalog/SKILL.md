---
name: checking-the-catalog
description: Use when about to write a new reusable function, class, config loader, formatter, or service wrapper in chat_app, mcp_server, or ai_agent — before writing implementation code — to check catalog_service for an existing @catalog-tagged building block first, instead of reinventing or hand-mirroring one found by grep.
---

# Checking the catalog

## Overview

`catalog_service` (repo root, port 8020) indexes every `@catalog`-tagged
function/class across chat_app, mcp_server, and ai_agent — three
independent codebases with **no cross-imports between them** (a
documented architectural invariant, see
`docs/System_Overview_Documentation.md`). So checking the catalog never
lets you *import* someone else's code — it lets you find an
already-solved interface/behavior before you re-derive one from
scratch or by grepping around for prior art.

**Check the catalog first, not as a fallback after grep.** Grepping
until you stumble on the analogous file gives the same destination
slower, and skips the one thing the catalog gives you that grep
doesn't: only *intentionally tagged* building blocks show up, not every
incidental function with a matching keyword.

## When to use

Before writing any new function/class that's more than a one-off inline
snippet in `chat_app/`, `mcp_server/`, or `ai_agent/` — a config loader,
validator, formatter, SSH/API client wrapper, cache, anything another
part of the repo plausibly already needed.

## How to check

**Live** (if the service is running):
```
GET http://localhost:8020/catalog
```
Returns `{"status": "ready"|"scanning", "entries": [...]}`. Filter
client-side by name/description keyword, or browse the UI at
`http://localhost:8020/`.

**Cache file** (works even if the service isn't running — never skip
the check just because it's down):
```
catalog_service/data/catalog_cache.json
```
Same entry shape either way: `id` (fully-qualified dotted), `type`,
`name`, `description`, `project`, `file`, `line`, `parameters`, and
`methods` for classes. `file`+`line` is where to go read the real
implementation — the cache entry itself is a pointer, not the source
of truth.

## On a hit

Open `file:line`, read the real implementation, and **mirror its
interface and edge-case handling** in the new project — same field
names, same validation rules, same error type — rather than inventing
a divergent shape. If the new context genuinely needs to differ, say
why in a comment.

## On a miss

Proceed. If what you write is itself a reusable building block, tag it
with the project's `@catalog` stub (`chat_app/src/utils/catalog.py`,
`mcp_server/src/utils/catalog.py`, `ai_agent/src/catalog.py`) so the
next scan finds it — `POST /catalog/refresh` to pick it up immediately
instead of waiting for the service's next boot.

## Rationalizations — check anyway

| Excuse | Reality |
|---|---|
| "Grep already found the analogous file" | The catalog is one HTTP call or one JSON read — faster than a 3-project grep, and it only surfaces things someone deliberately marked reusable. Grep is the fallback after a cache miss, not a substitute for checking. |
| "No cross-imports anyway, so there's nothing to reuse" | The value isn't sharing code via import — it's not re-deriving an already-solved interface independently in each project. |
| "Time pressure, no time to check" | The check is under 5 seconds. A second, subtly-diverging implementation costs far more later. |
| "I can tell what the pattern should look like" | That confidence is exactly how two near-identical, quietly inconsistent implementations end up in different projects. |

## Red flags

- About to write a config loader / parser / formatter / client wrapper without having queried `/catalog` or the cache file first.
- Grepping the repo for prior art *instead of* checking the catalog, rather than *after* a catalog miss.
- "I already know the pattern" without a file:line to point at.
