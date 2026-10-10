# Ascension rename: implementation plan

**Spec:** `docs/superpowers/specs/2026-10-11-ascension-rename-design.md`

**Goal:** Emberlings becomes Ascension, Sparks become Ascended, with Ascension's tiers and a new Ascension Types field.

**Order:** behaviour changes first (tiers, types) while the old names still exist, then the two mechanical renames.
Each task ends green (mini_games pytest, ember_api pytest, ember_web `vue-tsc`, Vitest, `vite build`) and is one commit.
ember_web steps are proposed and approved one task at a time; commits only on the user's word; pushes only on "push".

## Global constraints

- Code is object-oriented, as in the surrounding code.
- No literal `border-radius` values (`src/radiusScale.test.ts`).
- Never read `.env*`, `secrets/` or key files. Never run git at the workspace root.
- Stage only this work's files and hunks. Leave other sessions' uncommitted files alone
  (`apps/mcp_server` tickets, ember_web README ticket hunk, `e2e/fakeApi.ts` ticket parts, chat and tool-form files).
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

---

### Task 1: Ascension tier names and colours

**Files:**
- Modify: `apps/mini_games/configs/spark_catalog.json` (tier ids), `apps/mini_games/sparks/*/catalog.json` (any tier references)
- Modify: `apps/mini_games/src/sparks/*.py` where tier ids are literals, and `tests/sparks/*` that assert them
- Modify: `apps/Ember/ember_web/src/components/emberlings/theme.css` (`--em-tier-*` tokens), `ui/EmTierBadge.vue`,
  `SparkTemplateCard.vue`, `utils/emberlings.ts`, `EmberlingsClient.fixtures.ts`, and their tests
- Modify: `apps/Ember/ember_api` tests that use tier ids

- [ ] Grep for the six old ids (`normal`, `legendary`, `royalty`, `ascended`) in `apps/` Python, JSON, TS and Vue, to list exact sites.
- [ ] Rename the ids in the catalog and code with the spec table (do `legendary` to `unique` before `ascended` to `legendary`).
- [ ] Set the six colour tokens to the spec hex values; tier labels become Common, Rare, Unique, Royal, Legendary, Forbidden.
- [ ] Run all suites; fix assertions that named old tiers.
- [ ] Commit: `feat: Ascension tier names and colours`.

### Task 2: Ascension Types

**Files:**
- Create: `apps/mini_games/src/sparks/ascension_types.py` (a `StrEnum` of the six values plus label lookup)
- Modify: `apps/mini_games/src/sparks/catalog.py` (parse and validate `ascension_types`), `models.py`, `collection.py`, `api.py`
- Modify: `apps/mini_games/sparks/*/catalog.json` (add `"ascension_types": ["enchant"]` to all seven)
- Modify: `apps/mini_games/README.md` (document the field)
- Modify: ember_web `api/EmberlingsClient.ts` (types), `CollectionPanel.vue` (filter chips plus group-by-type toggle), `SparkTemplateCard.vue` (type chip on the large card), fixtures and tests
- Test: `tests/sparks/test_catalog.py`, `test_catalog_hardening.py` (unknown, duplicate and non-list values rejected; empty list allowed), `test_api.py`

- [ ] Failing catalog tests: valid list loads, unknown value fails, duplicate fails, missing field defaults to empty.
- [ ] Implement enum, loader and response field. Add `["enchant"]` to the seven catalog files.
- [ ] Failing Vitest for the Collection filter (all, one type) and grouping; implement.
- [ ] Run all suites. Commit: `feat: Ascension Types, filter and group the collection`.

### Task 3: Spark becomes Ascended (backend and API contract)

**Files:**
- Rename: `apps/mini_games/src/sparks` to `src/ascension`, `tests/sparks` to `tests/ascension`, `apps/mini_games/sparks` to `ascended`,
  `configs/spark_catalog.json` to `ascension_catalog.json`
- Modify: every `spark`/`Spark` identifier in mini_games (classes `SparkRecord`, `SqliteSparkRepository`, `build_spark_services`,
  `mount_sparks`, fields `spark_id`, table `sparks`), `src/run.py`, `README.md`, `pyproject.toml`, `run.bat`, config example
- Modify: DB `SCHEMA_VERSION` bump with the renamed table; README notes the old DB file must be deleted
- Modify: ember_api gateway, routes and tests for the renamed fields; ember_web client types, store, components, fixtures, e2e (`spark_id` to `ascended_id`, `Spark*` to `Ascended*`, user-facing "Spark" copy to "Ascended")

- [ ] `git mv` folders, then rename identifiers with a case-aware replace; do not touch unrelated matches (`Sparkline`, `StatTile`).
- [ ] Update the catalog loader constants (`SPARKS_PATH`, folder name) and the folder-equals-id rule.
- [ ] Run mini_games, ember_api, ember_web suites and the build; fix leftovers.
- [ ] Commit: `refactor: Spark becomes Ascended`.

### Task 4: Emberlings becomes Ascension

**Files:**
- Rename: `components/emberlings` to `components/ascension`, `stores/emberlings.ts`, `utils/emberlings.ts`, `EmberlingsClient*`, `EmberlingsView*`,
  `e2e/emberlings.spec.ts`, ember_api `routes/emberlings.py`, `services/emberlings_gateway.py`, their tests
- Modify: route `/emberlings` to `/ascension`, API prefix `/api/emberlings` to `/api/ascension`, permission `emberlings.play` to `ascension.play`
  (ember_api `permissions.py`, config validation, ember_web router, nav, `App.vue`, overview), page title and masthead copy,
  README and config examples, launcher entries if named
- Modify: docs (`docs/design/emberlings` to `docs/design/ascension`, spec and plan text where it describes the current game), `_TODO.md`,
  vault note `Brain/Projects/ember_web.md` and mini_games note, in the vault repo as its own commit
- Keep: historical spec and plan files keep their old file names (dated records); only a one-line note at the top points to the rename

- [ ] `git mv` files, replace identifiers and copy, update the permission everywhere including admin grants text.
- [ ] Final gate: grep the repo (excluding historical docs, zips, node_modules) for `emberling` and `spark` (case-insensitive); only intended leftovers remain.
- [ ] Run every suite and build. Commit: `refactor: Emberlings becomes Ascension`. Vault commit separately.
