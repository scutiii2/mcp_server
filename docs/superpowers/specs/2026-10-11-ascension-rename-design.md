# Ascension rename: design

Emberlings becomes Ascension. Sparks become Ascended. The tier names and colours follow the Ascension
Unity game, and each Ascended gains one or more Ascension Types.

Source of truth for the Unity side: `Game Developing/Unity 6/Ascension`
(`Assets/Scripts/Gameplay/Definitions/Tier.cs`, `Assets/Scripts/Gameplay/Entities/Units/AscendedType.cs`,
`Assets/Guides/Ascended.md`). Nothing is copied from Unity at run time; this spec records the values.

## Scope

1. Rename the game: Emberlings becomes Ascension, everywhere (code, URLs, permission, folders, copy, docs).
2. Rename the collectible: Spark/Sparks becomes Ascended (the plural is also "Ascended").
3. Use Ascension's tier names and colours.
4. Add Ascension Types, used only to filter and group for now.
5. Mark every current Ascended as Enchant.

Insignia (currency) and EMBLEM (catch item) keep their names. Roles from Ascension (`AscendedRole`) are out of scope.

## Tiers

Positions are kept; only ids, labels and colours change. Prices, thresholds and all numbers stay.

| Old id | New id | Colour |
|---|---|---|
| normal | common | grey `#9E9E9E` |
| rare | rare | green `#4CAF50` |
| legendary | unique | blue `#2196F3` |
| royalty | royal | purple `#9C27B0` |
| ascended | legendary | gold `#FFD700` |
| forbidden | forbidden | red `#F44336` |

The hex values tint the cards. Tier names written as text on the dark page use lighter versions of the same hues
(`--em-tier-*` in `theme.css`), so the purple and blue stay readable.

The old tier `ascended` disappears, so the word "Ascended" no longer clashes with the tier.
Ascension also defines Essence cost and Stars per tier. Those are not adopted: they have no use here.

## Ascension Types

Six types, a multi-select set per Ascended (zero or more): `pure`, `abyss` (Dark), `divine` (Light),
`crimson` (Blood), `enchant` (elemental), `synthetic` (Cyborg, Silicon).

- Stored in each Ascended's `catalog.json` as `"ascension_types": ["enchant"]`.
- Validated by the catalog loader: unknown value, duplicate or wrong type fails startup, like other catalog fields.
- Served on the catalog and collection responses as `ascension_types: string[]`.
- No gameplay effect. The UI uses them to filter the Collection and group it by type.
- All seven current Ascendeds (guardian, scout, striker, sentinel, channeler, bruiser, forbidden) are fire,
  so each gets `["enchant"]`.

## Naming map

| Old | New |
|---|---|
| Emberlings | Ascension |
| Spark / Sparks | Ascended |
| `spark_id`, `sparks` (API fields, DB) | `ascended_id`, `ascended` |
| `apps/mini_games/src/sparks`, `tests/sparks` | `src/ascension`, `tests/ascension` |
| `apps/mini_games/sparks/<id>/` | `apps/mini_games/ascended/<id>/` |
| `configs/spark_catalog.json` | `configs/ascension_catalog.json` |
| `/api/emberlings` | `/api/ascension` |
| permission `emberlings.play` | `ascension.play` |
| route `/emberlings`, `components/emberlings` | `/ascension`, `components/ascension` |
| `SparkCard`, `SparkTemplateCard`, `sparkArt` | `AscendedCard`, `AscendedTemplateCard`, `ascendedArt` |
| `.em-root`, `--em-*`, `Em*` primitives | unchanged (short prefix, not the game name) |

Plural note: the singular and plural are both "Ascended". Identifiers use `ascended` for a single record
and `ascended_list` or `ascendeds` is avoided; collections are named `roster` or by what they hold.

## Stored data

The mini_games SQLite file has a strict schema version and tables named `sparks`, plus tier ids in rows.
The rename bumps `SCHEMA_VERSION`. Existing saves are not migrated: the game is pre-release and the profile
data is test data. On the first start with an old file, the repository refuses it with the existing
"database schema version N is not supported" error, and the file is deleted by hand (documented in the README).

If saves turn out to matter, a one-off migration script can be added later; the table and tier maps above
are the full mapping.

## Not changing

- The product name "Ember" (ember_web, ember_api, ember_admin). Only the game's name changes.
- `mini_games` as the service name and port 8060.
- The Spark portraits and card frame art (files keep working; only their code names change).
- Test layout conventions, the radius scale rule, and the manual-testing workflow.

## Risks

- Large mechanical diff. It is split into four commits (see the plan) so each one is reviewable and green.
- A missed `spark` in a string shows as stale copy, not a crash. A repo-wide grep gate at the end catches this.
- Unrelated words match "spark" (`Sparkline.vue`, `StatTile.vue` in ember_admin). The rename leaves those alone.
- Other sessions have uncommitted work in `ember_web` and `mcp_server`. Those files are not touched; only
  hunks and files belonging to this work are staged.
