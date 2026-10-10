# Emberlings

> **Renamed 2026-10-11:** the game is now called Ascension and Sparks are Ascended (see `2026-10-11-ascension-rename-design.md`). This record keeps the names it was written with.

Date: 2026-10-10 (Asia/Manila).
Status: draft for user review; no implementation has started.

## Purpose and agreed scope

Add a Spark-collector game to the planned `apps/mini_games` service, with
Ember as its interface. Players collect Sparks, absorb duplicates, earn
Insignia, and assemble personality presets whose weights bias each Spark's
action choices. The engine applies the weights and rolls the action; local Laya
only reads the battle situation (see Action policy). Manual control remains
available. Success means the same authoritative rules apply to manual and
autonomous play, decisions remain private until reveal, autonomous Sparks do
not repeat one action predictably, and progression and active battles survive
restarts.

Naming (decided 2026-10-10): the game is **Emberlings** and its collectibles are
**Sparks**. Spark names are still working role labels. File names keep the
earlier working name so links stay valid.

Revision 2026-10-10: personality now acts through an engine-side action policy
instead of through Laya's choice. This supersedes the earlier "Laya selects the
action" design; the decision record carries the matching change.

V1 includes 1v1 wild encounters, seven Sparks, progression, collection, shops,
personality pools, presets, and persistent battles. NPC-player battles and human
multiplayer are excluded. Wild Sparks can obstruct escape but cannot collect
the player's Spark.

The complete approved gameplay and initial content tables are in
[the decision record](2026-10-09-emberlings-decisions.md). That record
contains the seven stat/growth tables, passives, active abilities, eight
personality profiles, tier thresholds, encounter probabilities, and prices.
This specification references those tables rather than maintaining competing
copies. Update both documents when an approved change affects this design.

The existing
[mini_games backend design](2026-10-09-mini-games-backend-design.md) supplies the
shared service foundation. This extension adds persistent progression and
simultaneous-choice rounds without changing chess or Tetris rules.

## Architecture

Use three boundaries within mini_games:

1. **Battle engine:** pure battle rules, legal actions, phase resolution,
   effects, passives, and terminal outcomes. It does not access SQLite, HTTP,
   browser state, or Laya directly. The action policy (`policy.py`) is also
   pure: situation values, personality weights, mood and history in; action
   probabilities and a seeded draw out.
2. **Spark service / round coordinator:** ownership, encounters, battle
   lifecycle, private choice locking, timed EMBLEM selection, Laya situation
   reads, and atomic progression/reward updates.
3. **SQLite repository:** durable records, transactions, idempotency,
   battle revisions, private RNG state, and recovery checkpoints.

A committed, versioned JSON catalog defines Sparks, abilities, personality
types, and initial balance values. Catalog loading and validation belong to
mini_games; no imports from other projects are required. Runtime data lives at
`apps/mini_games/data/sparks.sqlite3`, excluded from git.

Proposed layout:

```text
apps/mini_games/
  configs/spark_catalog.json
  src/sparks/
    catalog.py         # Catalog (loads and validates spark_catalog.json)
    models.py          # frozen value objects
    runtime.py         # Clock, RandomSource, seeded and recording randomness
    passives.py        # one class per Spark passive, PassiveFactory
    engine.py          # BattleEngine
    policy.py          # ActionPolicy and Mood: probabilities, mood, repeat penalty
    situation.py       # SituationReader and its implementations
    decider.py         # ActionDecider: one Spark's decision
    errors.py          # SparkError and its HTTP statuses
    records.py         # row values
    repository.py      # SparkRepository and SqliteSparkRepository
    idempotency.py     # IdempotentWriter
    progression.py     # ProgressionService (XP, copies, tiers, rewards)
    collection.py      # CollectionService (profile, personality pool, presets)
    encounters.py      # EncounterRoller and EncounterService
    shop.py            # ShopService
    battle_view.py     # BattleViewBuilder: the public battle JSON
    emblem_picker.py   # EmblemPicker and LayaEmblemPicker
    coordinator.py     # RoundCoordinator
    api.py             # routers: thin adapters over the services
    composition.py     # build_spark_services, the composition root
    simulation.py      # BattleSimulator: AI-against-AI battles
    eval/situation_eval.py   # manual Laya evaluation
  tests/sparks/
```

### Object-oriented structure

All code is object-oriented: one class per responsibility, behavior behind small
interfaces, collaborators passed in through constructors, and composition rather
than inheritance. Interfaces are `typing.Protocol` classes, so a test double needs
no base class. Data that crosses a boundary is an immutable dataclass.

| Class | Responsibility | Depends on (injected) |
|---|---|---|
| `Catalog` | Loads and validates the versioned JSON catalog; looks up Sparks, abilities, personalities, tier tables | none |
| `Spark`, `BattleSnapshot`, `Personality`, `Preset`, `RoundResult`, ... | Immutable value objects (frozen dataclasses) | none |
| `BattleEngine` | Pure rules: legal actions, phases, effects, damage, FLEE/CATCH math, terminal outcomes | `Catalog` |
| `ActionPolicy` | Pure: situation values, mood, personality weights and history in; action probabilities and a seeded draw out | `Catalog` (policy block) |
| `SituationReader` (Protocol) | `async read(public_state) -> Situation` | none |
| `LayaPartialSituationReader` | Asks the three typed questions through the Laya client; a value it cannot give is left empty | `LayaClient` |
| `HeuristicSituationReader` | Computes the heuristic values from public state | none |
| `FallbackSituationReader` | Composes a primary and a heuristic reader, falling back per question | two `SituationReader`s |
| `SparkRepository` (Protocol) | Async persistence interface: profiles, Sparks, personalities, presets, encounters, battles, rounds, idempotency | none |
| `SqliteSparkRepository` | Implements the interface over SQLite: transactions, constraints, revisions; blocking `sqlite3` calls run in a worker thread behind a write lock so the event loop never blocks | database path |
| `CollectionService` | Profile and starter, personality pool, five presets per Spark | `SparkRepository`, `IdempotentWriter`, `Catalog`, `Clock`, `RandomSource` |
| `IdempotentWriter` | Exactly-once mutations: the response is stored in the same transaction as the change | `SparkRepository`, `Clock` |
| `EncounterRoller` | Pure random draws behind an encounter (tier, Spark, level, personalities) | `Catalog` |
| `ActionDecider` | One Spark's decision: situation read, mood draw, probabilities, seeded draw | `Catalog`, `BattleEngine`, `ActionPolicy`, `Mood`, `SituationReader`, `SituationViewBuilder` |
| `BattleViewBuilder` | The public battle JSON, never private data | `BattleEngine`, `Catalog` |
| `BattleSimulator` | AI-against-AI battles for tuning and for checking personality behaviour | `Catalog`, `BattleEngine`, `ActionDecider` |
| `ProgressionService` | Copies, tiers, XP and levels, Insignia, personality awards; commits one terminal result atomically | `SparkRepository`, `Catalog` |
| `EncounterService` | Rolls and persists previews; enforces the 30-second limit and one-active-battle rule | `SparkRepository`, `Catalog`, `Clock`, `RandomSource` |
| `ShopService` | Purchases and sales with the pricing formulas | `SparkRepository`, `Catalog` |
| `RoundCoordinator` | Battle lifecycle: private choices, EMBLEM prompt deadlines, mode switches, forfeit, recovery, one resolved round at a time | `BattleEngine`, `ActionDecider`, `SituationViewBuilder`, `EmblemPicker`, `SparkRepository`, `IdempotentWriter`, `ProgressionService`, `BattleViewBuilder`, `Clock` |
| `EmblemPicker` (Protocol) | Chooses an EMBLEM tier after a timed-out prompt; `LayaEmblemPicker` implements it | `LayaClient` |
| `Clock`, `RandomSource` (Protocols) | Time and seeded randomness, so tests control both | none |

One composition root builds the object graph at startup (`build_spark_app`), and
the routers take the finished services. Extending the game (a new action category,
a different situation reader, another store) means adding a class that satisfies
an existing interface, not editing the coordinator. Everything that waits (SQLite,
Laya, deadlines) is `async`; the pure engine and policy stay synchronous and fast.

Reuse the planned Laya client, authenticated application, and port 8060.
Expose Spark-specific round routes rather than forcing this game through
the alternating-turn `/sessions/{id}/moves` contract. Game discovery advertises
the Spark game with its route family; legacy chess/Tetris session creation
does not accept a Spark battle as an alternating-turn session.

## Gameplay contract

### Collection and progression

- One owned Spark per kind of Spark; subsequent captures or purchases add copies.
- Regular copy thresholds are Normal 0, Rare 10, Legendary 40, Royalty 100,
  Ascended 250. Copies are retained, and reductions can cause downgrades.
- Forbidden is a separate fixed tier, capped at level 50 and 100 held copies.
  Regular Sparks cap at level 30.
- First captures and shop-unlocked Sparks start at level 1. Tier changes keep
  level and XP. Purchases preserve an already-owned Spark's level.
- Capture rewards are 1 / 2 / 3 / 4 / 5 copies for regular tiers, and 1 for
  Forbidden. Purchases use regular capture amounts; Forbidden is capture-only.
- At Forbidden's copy cap, capture still grants its personality, XP, and Insignia.
- A new player chooses Guardian, Striker, or Scout at Normal level 1 with zero
  copies, five Normal EMBLEMs, zero Insignia, and one uniformly selected tier-1
  personality equipped in preset 1.

Working Spark names for this backend are Guardian, Striker, Scout, Sentinel,
Bruiser, Channeler, and Forbidden. Stable catalog IDs are separate from display
names so presentation can be changed later without changing ownership.

### Stats and abilities

```text
Stat = (Spark base stat + per-level growth × (level − 1)) × tier multiplier
Ability magnitude = ESSENCE × ability percentage
Damage received = Raw damage × 100 / (100 + Defense rating)
```

HP, ESSENCE, and SPEED use the approved Spark bases and 10%-of-base growth.
Battle-stat tier multipliers are 1 / 1.25 / 1.5 / 2 / 2.5 / 4. ESSENCE is not
consumed. Each Spark has one passive and three catalogued active abilities,
unlocked at levels 1, 10, and 20. Basic ATTACK is 100% ESSENCE with no cooldown;
basic ATTACK, FLEE, and CATCH are outside the three active slots.

SUPPORT uses unbuffed ESSENCE. Reuse refreshes duration without increasing
strength; different buffs add bonuses. Buff duration includes activation round.
ATTACK and DEFENSE use current ESSENCE. Defense normally protects one attack
and expires at round end. Passive extensions can add protected attacks, rounds,
or both. Overlapping defense keeps the strongest rating; refresh resets limits
rather than banking protection.

Cooldown `d` after use in round `r` blocks rounds `r+1` through `r+d`; the
ability returns in round `r+d+1`. FLEE and CATCH have no cooldown.

### FLEE and CATCH

```text
Flee chance = ESSENCE / (100 + ESSENCE) × current HP / max HP
When facing CATCH:
  Final flee chance = Flee chance × 100 / (100 + catcher's ESSENCE)

Capture resistance = 100 × capture-tier multiplier
                     × [HP floor + (1 − HP floor) × current HP / max HP]
Capture chance = EMBLEM strength / (EMBLEM strength + Capture resistance)
```

These probabilities are fractions from 0 to 1; the UI displays percentages.
Capture-tier multipliers are 1 / 2 / 4 / 8 / 16 / 128, independently of battle
stat multipliers. HP floors are 10% / 20% / 35% / 50% / 65% / 80%. EMBLEM
strengths are 100 / 200 / 400 / 800 / 1,600 / 3,200.

CATCH against a revealed FLEE always reduces escape chance, regardless of
SPEED order, and does not attempt collection or consume an EMBLEM. Player CATCH
against another action attempts collection. Wild CATCH against a non-FLEE
action has no effect.

The player selects an EMBLEM before reveal. An actual collection attempt consumes
one whether it succeeds or fails. No attempt means no consumption. Autonomous
CATCH prompts for five seconds; after timeout Laya selects within the player's
pre-battle tier limit. Manual selection can exceed that limit. No permitted
EMBLEM at timeout, or a failed/invalid Laya selection, falls back to basic ATTACK
before reveal.

### Personality instances and presets

- Each wild Spark has 1–3 personality instances, with equal odds for count.
  Types are equally drawn from the eight approved profiles, with duplicates.
  Tier probabilities are 60% / 30% / 10%, independent of Spark rarity.
- Capture reveals all source personalities and uniformly awards one instance.
  Discarded source instances are visible in the capture result but not collected.
- Every award creates a distinct Spark-specific instance, including identical
  type/tier duplicates. No automatic upgrade, replacement, or lock mechanism.
- No gameplay pool-size cap. At most five presets per Spark and three distinct
  instance IDs per preset. Repeated types require separately acquired instances.
  An instance can be referenced by several presets.
- Matching weights add. Each personality's weight budget is 2 / 4 / 6 for tiers
  1 / 2 / 3; the combined Spark profile is not capped at six. Within a
  round the sum is mood-weighted (see Action policy), so a Spark with several
  personalities shows different moods instead of one fixed profile.
- Preset selection occurs before battle. Freeze its instance IDs and weights
  for that fight even if the saved preset is subsequently edited.
- Personality weights bias which action is sampled; they never change an
  action's potency or success chance. Weights alone never force an action.

### Rewards, recovery, and economy

```text
XP needed for next level = 100 × current level
XP reward = 20 × enemy level × enemy battle-stat tier multiplier
Insignia reward = 10 × enemy level × enemy battle-stat tier multiplier
Sale value = floor(Spark base price × current battle-stat tier multiplier
                   × [1 + 0.05 × (level − 1)])
Purchase price = 2 × copies granted
                 × per-copy sale value at resulting Spark tier and level
EMBLEM price = 20% of EMBLEM strength
```

Only player wins and successful captures grant XP and Insignia, equally for
either outcome. XP goes to the Spark that fought. Selling removes one copy,
can downgrade regular Sparks, never causes fainting, and cannot remove the
owned Spark. Zero copies means nothing to sell. The shop has unlimited stock
for all six regular Sparks and five regular tiers; no personalities are sold.

HP, temporary effects, and cooldowns reset between battles. Knockout and forfeit
cause five minutes of fainting at any tier without copy loss. Successful escape
does not cause fainting or award rewards. Player capture loss and zero-copy
capture fainting are retained in the decision record for future NPC battles;
they cannot occur in v1 wild encounters.

## Encounters and battle lifecycle

Preview the Spark, tier, and level, keeping personalities hidden. The player then
chooses a non-fainted Spark, preset, control mode, and autonomous EMBLEM limit.
Declining is free. Enforce one new roll per 30 seconds, starting at generation.

Draw encounter tier using the approved 60% / 25% / 10% / 4% / 0.9% / 0.1%
probabilities. Proposed default: regular tiers choose uniformly among the six
regular Sparks; Forbidden selects the sole Forbidden Spark. Draw enemy level
uniformly between `clamp(highest owned level − 2, 1, enemy cap)` and
`clamp(highest owned level + 2, 1, enemy cap)`. This handles a level-50 collection
producing regular enemies without an invalid level interval.

One active battle per player, including paused battles. Starting consumes the
saved encounter; clients cannot replay a preview to start more fights. Persist
catalog-versioned participant snapshots, the selected preset, and private RNG
state. Changing the chosen fighter after preview does not reroll the enemy.

Manual choices are untimed. Players can switch manual/autonomous mode between
rounds before the next action is locked. Closing the view finishes a fully locked
round, then pauses. If an EMBLEM prompt is unfinished, preserve its deadline;
resume handles an expired deadline through the approved Laya/fallback path,
without accepting a late answer. No new autonomous round starts while closed.

Forfeit is available for active and paused battles, serialized against resolution.
A completed result cannot be replaced by a late forfeit or another action.

## Round state machine and resolution

Persistent phases are `choosing`, `awaiting_emblem` and `terminal`. `locked` and
`resolved` happen inside one transaction and are never saved, so a crash cannot
leave a half-resolved round. Public responses describe required player input without exposing a
private wild action. A CATCH intent awaiting EMBLEM selection is not fully locked.

1. Build both decisions from the same public round state: manual input, or the
   action policy (situation reads, mood draw, probabilities, seeded draw). Store
   private choices; no Laya read ever receives the opponent's pending choice.
2. Complete any EMBLEM prompt or fallback, validate the choices, and lock both.
3. Reveal together. Apply SUPPORT, then DEFENSE; calculate defense ratings once
   at activation and retain those snapshots until expiration or refresh.
4. Establish all CATCH-vs-FLEE reductions before either escape attempt.
5. Roll once using updated SPEED:
   `P(A first) = SPEED_A / (SPEED_A + SPEED_B)`.
6. Resolve ATTACK, CATCH, and FLEE in that order of actors. DEFENSE/SUPPORT
   already used their action and do not execute again.
7. Stop immediately on knockout, successful capture, successful escape, or
   a serialized forfeit. Do not run later actions or spend unused EMBLEMs.
8. Otherwise expire end-of-round effects, update cooldown availability, save
   the checkpoint, and wait for the next round.

Terminal rewards, awarded personality, copies/tier, XP/level, wallet, inventory,
recovery/faint timestamp, and battle result commit in one SQLite transaction.
Persist random draws with the result; retries and restarts never reroll outcomes.

## Action policy and Laya situation reads

Personality and chance live in the engine; Laya reads the situation. A fixed
personality fed to a classifier would pick the same action every time, because
the same text gives the same answer. So the engine turns situation reads and
personality weights into action probabilities and samples the action, like the
SPEED order roll. The autonomous player Spark and wild Sparks use the same
policy. Manual play bypasses it.

### Inputs (public information only)

Both Sparks' HP fractions, stats, active effects and cooldowns, the revealed
action history, the Spark's own frozen personality weights, and its own
available actions. Never the opponent's personalities, pending or locked action,
private RNG state, or unauthorized inventory choices.

### Situation reads

One local Laya call asks three typed questions about a short public-state text
(using the planned typed-question client; shorten history before dropping state):

| Id | Type | Question | Value |
|---|---|---|---|
| `danger` | score, four levels: safe, pressured, endangered, critical | How much danger is this Spark in? | d = score / 3 |
| `enemy_aggression` | score, three levels: passive, mixed, aggressive | How aggressively has the enemy acted? | a = score / 2 |
| `advantage` | noul | Does this Spark have the upper hand? | t = probability |

Heuristic values, computed by the engine from public state, replace any read
that is uncertain (below the client's minimum confidence), invalid, late, or
unavailable, one question at a time:

```text
d = 1 − own HP fraction
a = enemy ATTACK share of revealed rounds (0.5 before round 2; Laya is not asked in round 1)
t = 0.5 + 0.5 × (own HP fraction − enemy HP fraction)
```

With no Laya at all (package missing, load failure, deadline), every value is
heuristic and the game still plays with personality-driven variety. Config
`situation_source` is `laya` or `heuristic`. A configurable two-second inference
deadline applies after the client is loaded. No external paid model or cloud
gateway is required.

### Action probabilities

For each legal action `x` (cooldowns, missing EMBLEMs and the like already
excluded) in action category `c(x)`:

```text
weight(x) = situation(c) × (1 + gain × W_c) × potency(x) × repeat(x)
P(x)      = weight(x) / Σ weight over legal actions
```

The engine draws from `P` with the battle's seeded, persisted RNG.

- Initial situation values per category (balance values in the catalog `policy`
  block, tuned by battle simulation, with a floor of 0.05):

  ```text
  ATTACK    = 0.5 + 0.8 t + 0.4 (1 − d)
  DEFENSE   = 0.3 + 0.9 d + 0.5 a
  SUPPORT   = 0.3 + 0.7 (1 − d) + 0.4 (1 − a)
  FEAR      = 0.05 + 1.2 d (1 − t)                       (FLEE)
  INTERCEPT = collecting Spark: 0.05 + 1.2 (1 − enemy HP fraction) (1 − d)
              wild Spark:       0.05 + enemy FLEE share of revealed rounds
                                   (0.1 before round 2)   (CATCH)
  ```

  So an AGGRESSIVE Spark still defends when its HP is nearly gone.
- `W_c`: the round's mood-weighted weight for category `c` (see Mood).
  `gain` defaults to 0.25: AGGRESSIVE 3 multiplies ATTACK by 1.75, not by 4.
- `potency(x)`: the action's ability percentage divided by the mean percentage of
  the available actions in its category; 1 for FLEE, CATCH, or a lone action.
  Stronger abilities are preferred within a category.
- `repeat(x) = 0.5^n`, where `n` is the number of immediately preceding rounds in
  which the Spark chose the same action. This breaks loops.
- Personality changes only which action is more likely, never its potency or
  success chance. No weight ever makes an action certain.

### Mood

Each round the engine draws one of the battle's frozen personality instances
uniformly (a single-instance Spark always uses it). The mood instance counts
fully; every other instance counts at `off_mood_factor` (default 0.5). Weights
then add per category. Example: AGGRESSIVE 3 `{ATTACK: 3}` with CAUTIOUS 2
`{DEFENSE: 2, FEAR: 2}`:

```text
mood AGGRESSIVE → W = {ATTACK: 3,   DEFENSE: 1, FEAR: 1}
mood CAUTIOUS   → W = {ATTACK: 1.5, DEFENSE: 2, FEAR: 2}
```

The mood draw is private, persisted with the round, and revealed only in the
finished-battle record.

### EMBLEM selection

Unchanged. When the autonomous player Spark's sampled action is CATCH, the
five-second EMBLEM prompt runs. After timeout, Laya chooses among at most six
owned, permitted tiers with a typed `choice` question. No permitted EMBLEM, a
failed or invalid choice, or an uncertain answer replaces CATCH with basic
ATTACK before reveal and consumes nothing. Wild Sparks never select EMBLEMs.

### Evidence for Laya's role

Do not assume the situation reads help. Run a real-model evaluation on matched
states and report: valid-and-confident rate per question, fallback rate, latency,
and whether `danger` rises as HP falls and `enemy_aggression` rises with the
enemy's ATTACK share. Then simulate battles with `situation_source` set to `laya`
and to `heuristic` and compare win and capture rates. If Laya's reads are no better
than the heuristics, ship `heuristic` and say so. Personality influence is
verified on the engine's own distributions, not on the model.

## Persistent model and API

SQLite records include player wallets/starter initialization; owned Sparks and
progress; EMBLEM balances; personality instances; presets and slots; encounters;
battles and participant snapshots; rounds with private choices, the mood draw,
the action probabilities and results; and idempotency responses. Unique constraints enforce owner/Spark ownership,
one active battle per owner, and preset/slot limits. All IDs are server-created.

Use the existing internal-token and requester-username boundary. Ownership comes
from the trusted requester header, not a body field. Foreign resources return
404, like missing resources. No client-supplied rewards, stats, chances, RNG
results, or personality grants are accepted.

Proposed Spark route family:

| Route | Purpose |
|---|---|
| `GET /sparks/catalog` | Public Sparks, abilities, tiers, and shop metadata |
| `POST /sparks/profile` | Initialize once with a starter Spark |
| `GET /sparks/profile` | Wallet, owned summaries, timers, pending encounter, and active battle |
| `GET /sparks/sparks/{id}/personalities` | Paginated collected instances |
| `GET/PUT /sparks/sparks/{id}/presets/{slot}` | Read/edit one of five presets |
| `POST /sparks/encounters` | Generate and persist one preview |
| `GET /sparks/encounters/{id}` | Reload the same owner-safe preview without rerolling |
| `POST /sparks/encounters/{id}/decline` | Decline without cost |
| `POST /sparks/battles` | Start the selected encounter and setup |
| `GET /sparks/battles/{id}` | Owner-safe state and revealed history |
| `POST /sparks/battles/{id}/actions` | Submit a manual action for a round |
| `POST /sparks/battles/{id}/emblem` | Answer the five-second prompt |
| `POST /sparks/battles/{id}/advance` | Drive an autonomous round or expired prompt |
| `POST /sparks/battles/{id}/mode` | Switch control mode at a round boundary |
| `POST /sparks/battles/{id}/forfeit` | End as a player loss |
| `POST /sparks/shop/purchases` | Buy EMBLEMs or regular-Spark copies |
| `POST /sparks/sparks/{id}/sales` | Sell one absorbed copy |

Mutations use an idempotency key. Round mutations also require the round number
and expected battle revision; stale or conflicting choices return 409. Repeat
requests with the same key and payload return the original result. Different
payloads reusing a key conflict. Invalid manual input returns a clear error;
only invalid AI choices trigger the AI fallback.

Proposed defaults: store timestamps as UTC, enforce deadlines on the server,
paginate personality instances with a default page size of 50 and maximum 100,
and reject sales/purchases changing the selected Spark while its battle is
active. Other Sparks and EMBLEM purchases may proceed transactionally.

## Other explicit technical defaults for review

- Compute Spark level/tier stats at full precision, then floor to positive
  whole-number stats. Floor applied buff magnitudes; sum raw damage and apply
  mitigation before flooring received damage. A positive attack deals at least
  one damage. V1 has no negative stats, resistances, or damage values.
- Carry excess XP through successive level-ups. At the Spark cap, stop gaining
  XP and discard excess beyond the final level-up. Tier changes do not reset XP.
- Do not provide personality deletion in the initial backend. Pools have no
  gameplay cap and presets reference persistent instance IDs.
- Let balance catalog changes affect future battles; active battles retain
  their saved version and participant/ability snapshots.
- Persist faint and encounter deadlines through restarts. Passage of real time
  counts while the application is closed; restarting does not reset timers.

These defaults are proposed engineering resolutions, not earlier user approvals.
Reviewing this written specification is the point to accept or change them.

## Verification and delivery boundaries

Meaningful tests cover phase order, same-round SPEED buffs, cooldown boundaries,
buff refresh/addition, strongest-defense refresh, passive limits, exact
FLEE/capture formulas, and terminal preemption. Seeded tests prove repeatability;
statistical checks validate the weighted order and tier/award distributions.

Policy tests cover: probabilities sum to 1 and exclude illegal actions; repeat
decay; potency within a category; mood draw frequency and mood-weighted sums;
heuristic values with no Laya and per-question fallback; AGGRESSIVE attacks more
and COWARD flees more over many seeded draws, while low HP still raises DEFENSE
and FLEE for every personality; saved RNG state gives the same draw after restart.

Repository/API tests cover ownership isolation, initialization once, distinct
duplicate personalities, five-preset/three-instance constraints, Spark scope,
copy thresholds/downgrades, Forbidden caps, XP overflow, price calculations,
insufficient funds/inventory, and no buy/resell profit from immediate resale.

Recovery/concurrency tests cover restart checkpoints, five-second deadlines,
late answers, mode-switch boundaries, one active battle, forfeit/resolution
races, and exactly-once rewards/EMBLEM consumption after retries or interruption.
Fault-injected Laya tests cover missing/failed/uncertain/invalid/late situation
reads and EMBLEM choices, and confirm that no private opponent data (personalities,
pending action, mood) enters a question or public response.

Run a separate real-Laya evaluation and simulated battles before calling the
initial content balanced. No real-Laya evaluation has been performed for this
game during planning.

Delivery order:

1. Shared mini_games service foundation, reusing the existing backend plan.
2. Spark catalog, engine, action policy and Laya situation reads, SQLite repository, coordinator,
   API, and verification as this backend extension.
3. A separate Ember proxy/UI specification for encounters, boards, collection,
   presets, shop, timer prompts, and resumed fights.
4. Optional later chat/MCP integration and NPC-player battles.

This document does not implement Ember screens, chat tools, NPC players, new
services, or Spark artwork. The next artifact after approval is a detailed
backend implementation plan, with dependencies on the shared service foundation
made explicit.
