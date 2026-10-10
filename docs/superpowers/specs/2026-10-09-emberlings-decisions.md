# Emberlings

Date: 2026-10-09 (Asia/Manila).
Last updated: 2026-10-10 (Asia/Manila).
Status: ongoing planning record, not an approved implementation specification.

This file records the decisions made while planning a Spark-collector game
for mini_games. Update it after each new decision. Keep confirmed requirements
separate from suggested formulas, balance values, and unresolved questions.
Do not treat a suggestion as approved simply because the conversation moved on.

## Confirmed decisions

### Scope and control

- V1 battles are 1v1 against wild AI Sparks. Multiplayer is outside v1.
- Extend the planned mini_games backend with a Spark battle engine and
  persistent Spark progression. Share its game API and Laya integration;
  Ember provides the game interface. Do not create a separate Spark-game
  service or embed the battle engine directly into ember_api.
- Use SQLite within mini_games for persistent game data, including per-player
  collections, copies, levels/XP, Insignia, EMBLEMs, personality instances,
  presets, faint expiry, and encounter-roll timestamps. Progression must survive
  service restarts without requiring a separate database service.
- The proposed technical structure separates the battle engine, a round
  coordinator for private choices and timed EMBLEM selection, and persistent
  storage. The existing alternating-turn, temporary-session plan needs an
  extension; it cannot alone represent this Spark game's round flow.
- Active battles also survive service restarts. Persist each round's state and
  locked choices so reopening Ember resumes the same fight. Commit resolved
  battle state, rewards, and EMBLEM consumption atomically to avoid duplicate
  processing. Do not reroll or reveal a saved private choice during recovery.
- When the player closes the game view, autonomous battles finish any already-
  locked round, then pause between rounds until the player returns. Do not begin
  additional autonomous rounds while the game view is closed. Persist the paused
  battle so reopening resumes it rather than generating a new encounter.
- Each player can have only one active battle at a time. Reopening the game
  resumes that battle; another encounter cannot start a second battle until
  the active fight ends. This limit also applies to paused battles.
- Players can forfeit an active battle, including a paused fight. Forfeit ends
  the battle as a player loss: no XP or Insignia, no absorbed-copy loss, and
  five minutes of fainting for the fighting Spark. Successful FLEE remains
  the escape option that avoids fainting.
- Wild Sparks cannot capture the player's Spark. Only NPC players can
  capture it. NPC-player battles are deferred to later versions; v1 contains
  wild encounters only. NPC players are not human multiplayer opponents.
- Player capture loss, capture-induced downgrades, and zero-copy capture fainting
  are future-version rules, not outcomes possible against v1 wild opponents.
  V1 still has knockout fainting, sale-induced downgrades, and player collection.
- The proposed virtual, tier-matched EMBLEM for wild capture attempts was not
  adopted. Wild Sparks can use CATCH solely as an escape counter.
- Players can control their Spark manually or autonomously.
- Manual action selection has no time limit: the battle waits for the player's
  choice. The five-second player-response timer applies only to the EMBLEM
  selection prompt during autonomous play, not manual action selection.
- Players can switch between manual and autonomous control between rounds,
  before the next action is locked. Switching does not change or replace an
  already locked action. The battle's personality preset remains fixed.
- **Superseded 2026-10-10:** ~~LayaAI is used for battle action decisions,
  including autonomous player Sparks and wild opponents.~~ Autonomous player
  Sparks and wild opponents now choose actions through an engine-side action
  policy (see "Action policy" below). Laya reads the battle situation and still
  chooses the EMBLEM tier after a timed-out prompt.
- **Superseded 2026-10-10 for actions:** ~~If Laya fails or returns an invalid
  action, use basic ATTACK.~~ A failed, uncertain, invalid or late situation read
  falls back to an engine heuristic for that question only. Basic ATTACK before
  reveal remains the fallback for a failed, invalid, uncertain or impossible
  EMBLEM selection. No EMBLEM is consumed by that fallback, and the fallback
  cannot inspect the opponent's selected action.
- Laya receives only information available to its side: both Sparks' public
  stats, active effects, and revealed action history, plus its own personalities
  and available actions. Do not disclose the opponent's hidden personalities
  or pending action. It may infer behavior from revealed previous rounds.
- Both sides choose privately before their actions are revealed together.
  An AI must not see the opponent's locked choice when selecting its own.
- Implementation is object-oriented (confirmed 2026-10-10): one class per
  responsibility, interfaces as protocols, constructor injection, composition over
  inheritance, immutable value objects, async for everything that waits. The class
  structure is in the backend design.

### Action policy (confirmed 2026-10-10)

- A fixed personality fed to Laya would make a Spark choose the same action
  every time: Laya is a classifier, so identical text gives an identical answer,
  and it does not reliably follow weights written in a prompt. Personality is
  therefore applied by the engine, not by Laya.
- Laya reads the situation with three typed questions: danger (four levels),
  enemy aggression (three levels) and advantage (yes/no). Engine heuristics
  replace any uncertain, invalid, late or missing read, one question at a time.
  With no Laya the game still plays with personality-driven variety.
- The engine turns situation values, personality weights, a per-action potency
  term and a repeat penalty into action probabilities, then samples with its
  seeded, persisted RNG. Personality weights remain preference-only; they never
  change potency or success chance and never make an action certain.
- Mood: each round the engine draws one equipped personality instance; it counts
  fully while the others count at half weight, then weights add per category.
  The draw is private and persisted with the round.
- Every autonomous Spark, player or wild, uses the same policy. Manual play
  bypasses it. The information boundary is unchanged: public state, revealed
  history and own personalities only.
- The initial formulas and numbers (gain 0.25, off-mood factor 0.5, repeat factor
  0.5, per-category situation values) are balance values to tune by simulation
  and are listed in the backend design. Whether Laya's reads beat the heuristics
  is to be measured before shipping `situation_source: laya`.

### Encounter preparation

- Preview the wild Spark's species, tier, and level before the player commits
  to battle. Its personalities remain hidden until successful capture.
- After seeing the preview, the player can choose their Spark, personality
  preset, and autonomous EMBLEM tier limit before entering battle.
- Encounters randomly select a species and Spark tier, with higher tiers
  appearing less often and Forbidden the rarest. Forbidden-only species must
  remain Forbidden rather than appearing in the regular tier progression.
- Initial encounter tier probabilities are:

  | Spark tier | Encounter chance |
  |---|---:|
  | Normal | 60% |
  | Rare | 25% |
  | Legendary | 10% |
  | Royalty | 4% |
  | Ascended | 0.9% |
  | Forbidden | 0.1% |

- These probabilities total 100%. Forbidden appears once per 1,000 encounters
  on average, not as a guarantee or a pity counter. Rates are initial balance
  values subject to tuning.
- Generate enemy levels within two levels of the player's highest-level owned
  Spark, bounded to levels 1–30 for regular Sparks and 1–50 for Forbidden.
  Use the collection's level before preview; choosing a different battle Spark
  afterward does not regenerate the encounter. Tier adds difficulty independently.
- If the player's highest level exceeds a regular enemy's level cap, the raw
  ±2 range can have no overlap with valid levels. Specify how to clamp that
  range before implementation; the sampling distribution is also not finalized.
- Players can decline an encounter preview for free. New encounters can be
  generated only once every 30 seconds, measured from generation of the previous
  encounter, to prevent instant repeated rolls for rare tiers.
- Species-selection weights still need defining.

### New-player starting setup

- A new player starts with one Normal, level-1 starter Spark with zero
  absorbed copies.
- The starter includes one random personality so autonomous play is available.
  This is an explicit exception to personalities normally being capture-only.
- Choose that starter personality at tier 1, with equal odds among the eight
  v1 types, and automatically equip its collected instance in the starter's
  first personality preset.
- The player starts with five Normal EMBLEMs and zero Insignia.
- Players choose their starter from three regular species. Their species
  identities still need defining; initial stats and ability sets are below.

### V1 species roster

- V1 has six regular species and one Forbidden species.
- Three of the regular species are offered as starter choices.
- The other species are collected through encounters or regular-species shop
  purchases; the Forbidden species remains capture-only.
- Species identities remain to be designed. Initial stats, growth values,
  passives, active abilities, and base prices are recorded in this document.
- The three starter roles have these initial level-1 Normal base stats:

  | Starter role | HP | ESSENCE | SPEED |
  |---|---:|---:|---:|
  | Guardian | 150 | 20 | 15 |
  | Striker | 100 | 30 | 20 |
  | Scout | 120 | 22 | 35 |

- Guardian emphasizes survival, Striker ability strength, and Scout acting
  first. These are role labels and initial balance values, not finalized
  Spark names or evidence from balance simulations. Scout still uses the
  probabilistic SPEED order rule.
- Initial starter growth per level is 10% of each species' corresponding base
  stat, added linearly before the Spark-tier multiplier:

  | Starter role | HP growth | ESSENCE growth | SPEED growth |
  |---|---:|---:|---:|
  | Guardian | +15 | +2 | +1.5 |
  | Striker | +10 | +3 | +2 |
  | Scout | +12 | +2.2 | +3.5 |

- Keep fractional growth values in the definitions. Final stat rounding still
  needs defining; growth for the other species remains open.
- Initial starter passives, available from level 1, are:

  | Starter role | Passive effect |
  |---|---|
  | Guardian | DEFENSE protects against two attacks for up to two rounds. |
  | Striker | Below 50% HP, attacks add raw damage equal to 20% of current ESSENCE. |
  | Scout | At battle start, gains SPEED equal to 50% of unbuffed ESSENCE for that battle. |

- Guardian protection ends on its second protected attack or at its two-round
  expiry, whichever comes first, following the confirmed defense rules.
- Striker's added damage is part of the attack's raw damage before mitigation;
  "below 50%" excludes exactly half HP. Current ESSENCE can include buffs.
- Scout's battle-start bonus uses ESSENCE before temporary buffs, is applied
  once per battle, and expires with the battle. It can coexist with distinct
  SUPPORT bonuses under the additive-bonus rule.
- Initial starter active ability sets are:

  | Starter role | Level 1 | Level 10 | Level 20 |
  |---|---|---|---|
  | Guardian | DEFENSE: 200% ESSENCE; cooldown 1 | SUPPORT: ESSENCE bonus equal to 50% unbuffed ESSENCE; duration 2 rounds; cooldown 2 | ATTACK: 150% ESSENCE; cooldown 2 |
  | Striker | ATTACK: 150% ESSENCE; cooldown 1 | SUPPORT: ESSENCE bonus equal to 50% unbuffed ESSENCE; duration 2 rounds; cooldown 2 | DEFENSE: 100% ESSENCE; cooldown 1 |
  | Scout | SUPPORT: SPEED bonus equal to 100% unbuffed ESSENCE; duration 2 rounds; cooldown 2 | ATTACK: 125% ESSENCE; cooldown 1 | DEFENSE: 150% ESSENCE; cooldown 1 |

- Cooldowns are measured in full subsequent rounds as defined below. SUPPORT
  durations include the activation round. Guardian's passive extends DEFENSE;
  the other starters use default one-attack protection expiring that round.
- These are initial ability balance values, subject to battle simulation and
  tuning. Ability names remain to be chosen.
- The remaining species have these initial base stats, before tier scaling:

  | Species role | Base HP | Base ESSENCE | Base SPEED |
  |---|---:|---:|---:|
  | Sentinel | 180 | 18 | 10 |
  | Bruiser | 140 | 28 | 12 |
  | Channeler | 90 | 25 | 25 |
  | Forbidden species | 200 | 40 | 30 |

- These four species also gain 10% of each corresponding base stat per level,
  added linearly before tier scaling. Their per-level HP/ESSENCE/SPEED growth is
  Sentinel 18/1.8/1, Bruiser 14/2.8/1.2, Channeler 9/2.5/2.5, and Forbidden
  20/4/3. Together with the starters, this confirms 10%-of-base growth for the
  whole initial roster.
- At level 1, the Forbidden species' ×4 multiplier yields 800 HP, 160 ESSENCE,
  and 120 SPEED. Its role label is not yet a finalized Spark name.
- Initial passives for the remaining species are:

  | Species role | Passive effect |
  |---|---|
  | Sentinel | DEFENSE gains additional rating equal to 50% of unbuffed ESSENCE. |
  | Bruiser | Against an opponent choosing DEFENSE, ATTACK adds raw damage equal to 25% of current ESSENCE. |
  | Channeler | Its SUPPORT buffs last one extra round. |
  | Forbidden species | Species-specific active cooldowns are reduced by one round, to a minimum of one. |

- Sentinel modifies a defense activation's rating, not a separate stacking
  defense effect. Its added rating uses ESSENCE before temporary buffs.
- Bruiser's bonus is calculated at attack resolution from current ESSENCE,
  including buffs, and added before defense mitigation. It uses the opponent's
  revealed DEFENSE choice, not information available during private selection.
- Channeler's extension adds one round to its SUPPORT ability's base duration.
- Forbidden's reduction applies to species-specific active abilities, not
  basic ATTACK, FLEE, or CATCH, which already have no cooldown.
- Initial active ability sets for the remaining species are:

  | Species role | Level 1 | Level 10 | Level 20 |
  |---|---|---|---|
  | Sentinel | DEFENSE: 300% ESSENCE; cooldown 1 | SUPPORT: ESSENCE bonus equal to 50% unbuffed ESSENCE; duration 2 rounds; cooldown 2 | ATTACK: 125% ESSENCE; cooldown 2 |
  | Bruiser | ATTACK: 175% ESSENCE; cooldown 1 | DEFENSE: 100% ESSENCE; cooldown 1 | SUPPORT: ESSENCE bonus equal to 50% unbuffed ESSENCE; duration 2 rounds; cooldown 2 |
  | Channeler | SUPPORT: ESSENCE bonus equal to 75% unbuffed ESSENCE; duration 2 rounds; cooldown 2 | ATTACK: 125% ESSENCE; cooldown 1 | DEFENSE: 100% ESSENCE; cooldown 1 |
  | Forbidden species | ATTACK: 200% ESSENCE; cooldown 2 | DEFENSE: 300% ESSENCE; cooldown 2 | SUPPORT: ESSENCE bonus equal to 100% unbuffed ESSENCE; duration 2 rounds; cooldown 3 |

- The table lists base cooldowns and durations. Channeler's passive extends
  its SUPPORT duration from two rounds to three. Forbidden's passive changes
  its listed cooldowns from 2 / 2 / 3 to 1 / 1 / 2.
- ATTACK and DEFENSE use current ESSENCE; SUPPORT uses unbuffed ESSENCE.
  These initial ability values remain subject to balance simulation and tuning.

### Sparks and abilities

- Spark stats include HP, ESSENCE, and SPEED.
- Each species defines its own base HP, ESSENCE, and SPEED. Members of the
  same species share these base stats; species differences create distinct
  battle styles, and personalities supply behavioral variation.
- HP, ESSENCE, and SPEED use linear, species-specific level growth followed by
  a Spark-tier multiplier:

  ```text
  Stat = (species base stat + growth per level × (level − 1))
         × Spark-tier multiplier
  ```

- Each species defines separate base and per-level growth values for HP,
  ESSENCE, and SPEED. Tier changes recalculate stats without changing level.
  Numerical growth values and rounding remain to be defined.
- Initial Spark-tier stat multipliers apply to HP, ESSENCE, and SPEED:

  | Spark tier | Stat multiplier |
  |---|---:|
  | Normal | ×1.00 |
  | Rare | ×1.25 |
  | Legendary | ×1.50 |
  | Royalty | ×2.00 |
  | Ascended | ×2.50 |
  | Forbidden | ×4.00 |

- These are initial balance values to tune through battle simulations, not
  measured evidence of balanced play. Forbidden also has its level-50 cap.
- ESSENCE is a power stat, not a spendable resource. Using abilities does not
  consume ESSENCE; ability strength scales from ESSENCE and availability is
  governed by cooldowns.
- Each Spark can have one passive ability and up to three active abilities.
- Each species has a fixed species-specific ability set: one passive and up to
  three active abilities in v1. Personalities affect how Laya uses that set,
  rather than changing which abilities the species has.
- The passive and first species-specific active ability unlock at level 1.
  The second active unlocks at level 10 and the third at level 20, if those
  abilities exist in the species' set.
- Basic ATTACK, FLEE, and CATCH are available from the start, separate from
  the three species-specific active ability slots. This confirms the previously
  proposed universal-action slot accounting for FLEE and CATCH.
- Every Spark has an always-available basic ATTACK with no cooldown,
  separate from its three active ability slots. Its rating is 100% of ESSENCE:
  40 ESSENCE deals 40 raw damage before defense reduction.
- Ability magnitudes use percentage ratings multiplied by ESSENCE.
- ATTACK deals damage to enemies.
- DEFENSE reduces received damage.
- SUPPORT buffs the Spark itself.
- Reusing the same SUPPORT ability refreshes its buff duration instead of
  stacking its strength. Each SUPPORT ability contributes at most one active
  copy of its buff. Buffs from different SUPPORT abilities can coexist.
- Different SUPPORT buffs affecting the same stat add their bonuses together,
  rather than multiplying them. Base SPEED 50 with bonuses of +10 and +15
  becomes SPEED 75.
- SUPPORT buff magnitudes use the Spark's ESSENCE before temporary buffs,
  including its normal species, level, and Spark-tier scaling. Refreshing an
  ESSENCE buff cannot strengthen that buff recursively: with 100 unbuffed
  ESSENCE, a 20% ESSENCE buff grants +20 each time.
- ATTACK and DEFENSE can benefit from temporarily increased ESSENCE. Within-round
  timing for DEFENSE relative to new SUPPORT effects still needs specifying.
- Buff durations include the activation round. A two-round buff activated in
  round 1 applies during rounds 1 and 2, then expires at the end of round 2.
  Each SUPPORT ability defines its own duration; refreshing it restarts that
  duration from the refresh round.
- Use ability-specific cooldowns to limit repeated use, rather than relying on
  spending ESSENCE for that purpose. An ability on cooldown cannot be selected
  in either manual or autonomous control.
- Cooldowns count full rounds after use. An ability used in round 1 with a
  one-round cooldown is unavailable in round 2 and available again in round 3;
  a two-round cooldown blocks rounds 2 and 3, returning in round 4.
- Species-specific ability cooldown lengths remain to be assigned. Whether
  selecting an action that never resolves starts its cooldown needs defining.
- Every Spark also has universal FLEE and CATCH actions outside the three
  species-specific active ability slots.
- Wild Sparks cannot use CATCH to collect the player's Spark; that
  capability is restricted to NPC players. Wild CATCH can only obstruct FLEE;
  it applies the normal ESSENCE-based escape reduction and uses no EMBLEM.
- If the player does not choose FLEE, wild CATCH makes no collection attempt.
- FLEE and CATCH have no cooldown. Collection attempts still require and consume
  an EMBLEM; escape-counter CATCH consumes none.
- FLEE belongs to FEAR; CATCH belongs to INTERCEPT.
- The former names were reversed: INTERCEPT is no longer the action name,
  and CATCH is no longer the category name.

### Hidden personalities

- Sparks have hidden personalities that influence battle decisions.
- Each Spark can have up to three personalities.
- Every wild Spark has one to three personality instances, ensuring each
  successful capture can award one personality.
- Wild personality counts of one, two, or three are equally likely. For each
  instance, select its type equally from the eight v1 personality types,
  allowing duplicate types, and independently select its tier with initial
  probabilities of 60% tier 1, 30% tier 2, and 10% tier 3.
- Personality tier selection is independent of Spark rarity. Regular
  low-rarity encounters can still yield tier-3 personalities. Capture then
  awards one source instance uniformly, following the confirmed award rule.
- Personality profiles do not evolve automatically through leveling or Spark
  tier changes. Equipped personalities can be changed through player presets.
- Each player has only one captured active Spark per species. Later captures
  of that species are absorbed into that Spark rather than retained as
  separate playable individuals. This supersedes separate-individual ownership.
- Personality pools are scoped to the player's collected species: personalities
  acquired from a species can only be equipped by that species. Duplicate
  captures contribute to that species' Spark and personality pool.
- Each capture awards one randomly selected personality from the captured
  Spark to the player. The user has not specified that the source loses it.
- Players can create personality presets and equip them for captured Sparks
  to vary autonomous battle decisions. A Spark still equips at most three
  personalities; the collected pool is not limited to three by that rule.
- Each Spark can have up to five personality presets.
- V1 has no gameplay cap on stored personality instances. Duplicate entries
  remain distinct; the equipped three-personality and five-preset limits still
  apply independently of pool size.
- There is no personality-lock mechanism. Players manage equipped combinations
  through presets instead.
- This pool/preset approach replaces choosing immediate personality replacements
  on capture. Personality locks and the all-locked prompt-skip rule are removed.
- Collected personalities are separate entries, including entries with the
  same personality type and tier. Receiving another AGGRESSIVE 2 adds another
  AGGRESSIVE 2 entry; it does not overwrite an existing entry.
- Receiving a higher-tier personality does not automatically upgrade an
  existing entry or any preset. AGGRESSIVE 1 remains available when AGGRESSIVE 2
  is collected. This supersedes the highest-tier-only pool rule.
- Presets retain the exact collected personality entries selected by the player;
  players explicitly edit a preset to use a different entry or tier.
- Captures still award Spark copies and Insignia alongside the randomly
  selected personality, including duplicate type/tier personality awards.
- A preset can equip multiple instances of the same personality type if the
  player acquired those instances separately. A single collected instance
  cannot fill multiple slots in the same preset.
- The same collected instance can be referenced by different presets. Presets
  are alternative loadouts, and only one preset is active for a Spark at a
  time. Sharing an instance between presets does not consume or duplicate it.
- Select the active personality preset before entering battle. Its equipped
  personality instances stay fixed for that battle; switching or editing a
  preset cannot change the personalities used by an ongoing fight.
- Repeated-type instances add their weights normally. Three separately acquired
  AGGRESSIVE 3 instances, each with {ATTACK: 3}, produce {ATTACK: 9}.
- Wild Sparks' personalities are hidden before capture. A successful capture
  reveals all of that Spark's personalities, including those not awarded
  (the discarded personalities).
- Only one personality instance is awarded to the player's species pool.
  Every personality instance on the captured Spark has an equal selection
  chance, regardless of its type or tier. With three instances, each has a
  one-in-three chance. Discarded instances are revealed but not added to the pool.
- The recipient pool is the captured Spark's species pool. The precise award
  timing still needs defining.
- Each personality has three tier levels.
- Per-personality total weight budgets grow with personality tier:

  | Personality tier | Maximum total weight |
  |---|---:|
  | 1 | 2 |
  | 2 | 4 |
  | 3 | 6 |

- These are maximum budgets, not required totals. AGGRESSIVE 3 = {ATTACK: 3}
  remains valid; a mixed tier-3 profile can use
  {ATTACK: 3, DEFENSE: 2, FEAR: 1}. The mixed profile is an example, not a
  confirmed named personality.
- A personality can assign weights to multiple action categories.
- Its category weights total at most six points.
- The six-point limit applies independently to each personality, not to the
  Spark's combined personality weights. Three personalities can therefore
  contribute up to eighteen points in total.
- Combine personalities by adding weights for matching action types. For
  example, AGGRESSIVE 3 = {ATTACK: 3} and BOLD 2 = {ATTACK: 2, SUPPORT: 2}
  combine into {ATTACK: 5, SUPPORT: 2}.
- The engine's action policy (see Action policy) combines these preferences with
  the battle situation and currently available actions. Weights are decision
  biases, not a rule that the highest-weight action must always be chosen.
- Examples supplied by the user: AGGRESSIVE 3 = {ATTACK: 3},
  DEFENSIVE 3 = {DEFENSE: 3}, SUPPORTIVE 3 = {SUPPORT: 3}.
- COWARD 3 = {FEAR: 3}.
- All personality weights affect action preference only, not action potency
  or success probability. In particular, FEAR makes FLEE more likely to be
  chosen; it does not increase escape success. INTERCEPT makes CATCH more
  likely to be chosen; it does not strengthen its effect.
- Suggested terminology: "action types" for categories and "personality
  weights" for decision biases. The terminology itself is not yet finalized.
- The initial v1 personality catalog has eight types:

  | Personality | Weighted action types |
  |---|---|
  | AGGRESSIVE | ATTACK |
  | DEFENSIVE | DEFENSE |
  | SUPPORTIVE | SUPPORT |
  | COWARD | FEAR |
  | TENACIOUS | INTERCEPT |
  | BOLD | ATTACK, SUPPORT |
  | CAUTIOUS | DEFENSE, FEAR |
  | DISCIPLINED | DEFENSE, SUPPORT |

- Each listed action type receives weight equal to the personality tier: 1,
  2, or 3. Pure profiles total 1 / 2 / 3 points; mixed profiles total
  2 / 4 / 6 and fit the per-personality budgets. BOLD 3 is
  {ATTACK: 3, SUPPORT: 3}. BOLD is now a confirmed catalog entry, superseding
  its earlier use only as an illustrative name.

### Round resolution and SPEED

- SPEED was initially removed, then restored to decide action order through
  weighted randomization, rather than always letting the faster Spark act
  first.
- Both actions are locked and revealed before resolution.
- DEFENSE and SUPPORT activate first.
- SPEED changes from SUPPORT apply to the current round: after those effects
  activate, the engine rolls action order using the updated SPEED values.
- The game engine, not Laya, performs the weighted random roll:

  ```text
  P(A acts first) = SPEED_A / (SPEED_A + SPEED_B)
  ```

- Lower SPEED still has a chance to act first. SPEED 60 against 40 gives
  60% versus 40% odds; equal positive SPEED gives 50/50. Minimum SPEED,
  zero-value handling, and seeded randomness still need specifying.
- ATTACK, CATCH, and FLEE then resolve in the rolled order.
- Knockout, successful capture, or successful escape ends the battle immediately;
  an unresolved later action does not execute after the battle has ended.
- Player forfeit is an additional terminal exit, treated as a loss with the
  five-minute faint penalty. A forfeit must not allow later round actions or
  reward processing to continue after the terminal result.
- CATCH always applies its escape reduction when the opponent chooses FLEE,
  regardless of the rolled order. Its escape-counter effect must be established
  before the FLEE success roll.
- How to order competing DEFENSE/SUPPORT effects still needs defining.

### Defense

- Use diminishing-returns mitigation:

  ```text
  Defense rating = ESSENCE × defense ability percentage
  Damage received = Raw damage × 100 / (100 + Defense rating)
  ```

- Default protection covers one incoming attack.
- Unused protection expires at the end of the round; it does not carry over.
- Passive abilities can extend protection by additional protected attacks,
  additional rounds, or both. Each passive specifies its limits.
- Extended protection ends when its protected-attack allowance is exhausted or
  its duration expires, whichever comes first. For example, protection against
  two attacks lasting two rounds expires after those rounds even if unused.
- Overlapping defense effects do not stack their ratings. If a passive extends
  existing protection and another DEFENSE ability is used, retain the strongest
  defense rating and refresh protection with the new use.
- Refreshing defense resets its protected-attack allowance and duration to the
  new activation's limits, including applicable passive extensions, instead of
  adding to unused attacks or remaining rounds. Refreshing two-attack protection
  restores two attacks; it does not bank extra protection. Keep the strongest
  overlapping rating as above.
- Separate physical/magic resistances, negative resistance, and penetration
  shown in the reference image were not adopted as requirements.

### Escape, CATCH, and EMBLEMs

- FLEE success decreases as the fleeing Spark's remaining HP decreases.
- FLEE's base success chance should depend on ESSENCE, replacing the initial
  fixed 50% full-HP starting chance.
- Use this initial FLEE formula for all Spark tiers, before CATCH reduction:

  ```text
  Flee chance = 100% × ESSENCE / (100 + ESSENCE)
                × current HP / max HP
  ```

- At 100 ESSENCE, FLEE has a 50% chance at full HP and 25% at half HP.
  Capture difficulty remains a separate calculation using capture resistance.
- CATCH reduces escape probability using the same diminishing-returns approach
  as defense when the opposing Spark chooses FLEE.
- CATCH's escape-counter rating is 100% of the catching Spark's ESSENCE:

  ```text
  Final flee chance = Flee chance × 100 / (100 + catcher’s ESSENCE)
  ```

- A catcher with 100 ESSENCE halves escape odds. The reduction applies whenever
  CATCH faces FLEE, regardless of SPEED order, and consumes no EMBLEM.
- If the opponent does not choose FLEE, CATCH attempts to collect it through
  an EMBLEM. Lower target HP makes collection easier.
- EMBLEMs have tiers corresponding to Spark tiers.
- EMBLEM tier provides capture strength: a lower-tier EMBLEM can still attempt
  to collect a higher-tier Spark; there is no minimum-tier eligibility gate.
- Every collection attempt consumes one EMBLEM, whether it succeeds or fails.
- The player selects an EMBLEM when locking in CATCH, before seeing the wild
  Spark's chosen action. Consume that selected EMBLEM only when a collection
  attempt actually resolves, regardless of the attempt's success.
- In autonomous mode, the player sets the maximum EMBLEM tier permitted before
  battle. When autonomous control chooses CATCH, prompt the player to select
  an EMBLEM and allow five seconds to answer before revealing the actions.
- If the player does not answer within five seconds, Laya chooses an available
  EMBLEM within the player's permitted tier limit. This replaces the proposed
  automatic strongest-available selection by the engine.
- The tier limit restricts Laya's automatic selection only. A manual response
  can explicitly select any owned EMBLEM, including one above that limit.
- If the five-second prompt expires and no owned EMBLEM is available within
  Laya's permitted tier limit, replace CATCH with basic ATTACK before reveal.
  The fallback cannot inspect the opponent's selected action or spend an
  EMBLEM above the limit.
- If Laya fails or returns an invalid EMBLEM choice after the player prompt
  expires, replace CATCH with basic ATTACK before reveal and consume no EMBLEM.
- If the wild Spark chooses FLEE, CATCH counters escape and the selected
  EMBLEM is retained. If the battle ends before the player's collection action
  resolves, no collection attempt occurs and its EMBLEM is retained.
- Using CATCH to counter FLEE consumes no EMBLEM; that interaction obstructs
  escape rather than attempting collection.
- Higher Spark tiers are harder to collect. The intended low-HP resistance
  behavior uses higher tier resistance multipliers and HP floors, so higher
  tiers retain more capture resistance even at low HP.
- Forbidden Sparks are the hardest to collect.
- Forbidden retains at least 80% of its full-health capture resistance,
  regardless of how low its remaining HP is. Use an 80% HP floor as the initial
  balance rule; reducing HP still helps, but only removes up to 20% of resistance.
- Initial capture-resistance HP floors for every tier are:

  | Spark tier | Minimum full-health resistance retained |
  |---|---:|
  | Normal | 10% |
  | Rare | 20% |
  | Legendary | 35% |
  | Royalty | 50% |
  | Ascended | 65% |
  | Forbidden | 80% |

- Lowering HP helps more against lower tiers and progressively less against
  higher tiers. These are initial balance values, subject to later tuning.
- The capture model presented with this rule is:

  ```text
  Full-health resistance = species base resistance × tier multiplier
  Capture resistance = Full-health resistance
                       × [HP floor + (1 − HP floor) × current HP / max HP]
  Capture chance = 100% × EMBLEM strength
                  / (EMBLEM strength + capture resistance)
  ```

- Initial EMBLEM strengths and capture-resistance tier multipliers are:

  | Tier | EMBLEM strength | Capture-resistance multiplier |
  |---|---:|---:|
  | Normal | 100 | ×1 |
  | Rare | 200 | ×2 |
  | Legendary | 400 | ×4 |
  | Royalty | 800 | ×8 |
  | Ascended | 1,600 | ×16 |
  | Forbidden | 3,200 | ×128 |

- Capture-resistance multipliers are separate from battle-stat multipliers.
  For a species with base resistance 100, a matching EMBLEM gives 50% success
  at full HP for regular tiers, but 20% for Forbidden. Forbidden's 80% floor
  limits the low-HP chance to approximately 23.8% with its matching EMBLEM.
- Every species uses 100 base capture resistance in v1. Spark tier and
  remaining HP determine capture difficulty; species still differ through
  battle stats, abilities, and personalities. Species-specific base capture
  resistance can be considered in later versions.
- The earlier illustrative Forbidden resistance of 1,000 and EMBLEM strength
  of 100 were examples, superseded as balance guidance by the table above.
- Forbidden Sparks are obtainable only through wild capture, not Spark
  shop purchases.
- Forbidden EMBLEMs are purchasable with Insignia and have the highest EMBLEM
  price. Lower-tier EMBLEMs can still attempt Forbidden captures under the
  capture-strength rule; their weaker strength gives lower success chances.

### Levels, tiers, and absorbed copies

- Regular tiers, in order: Normal, Rare, Legendary, Royalty, Ascended.
- Regular Sparks have levels 1 through 30.
- Initial XP requirement for the next level is 100 × current level. Level 1
  needs 100 XP, level 10 needs 1,000 XP, and level 29 needs 2,900 XP to reach
  level 30. Regular Sparks stop at 30; Forbidden continues to its cap of 50.
- Only winning a battle or successfully capturing the enemy awards XP, matching
  Insignia eligibility. XP goes to the player's Spark that fought. Losses
  and escapes grant no XP.
- Initial battle XP reward is 20 × enemy level × enemy Spark-tier stat
  multiplier. A level-10 Normal awards 200 XP; a level-10 Legendary awards
  300 XP. Winning and successful capture award the same XP, with capture also
  granting its absorbed-copy and personality rewards.
- Both tier and level affect ESSENCE.
- Spark tier upgrades and downgrades preserve earned level and XP. Recalculate
  tier-dependent stats for the new tier without resetting level progression.
- Progression uses collected copies of the same Spark, with requirements
  that vary by tier. This replaces the original five-same-tier-Spark upgrade
  proposal.
- Regular tier follows cumulative absorbed-copy thresholds:

  | Tier | Total absorbed copies required |
  |---|---:|
  | Normal | 0 |
  | Rare | 10 |
  | Legendary | 40 |
  | Royalty | 100 |
  | Ascended | 250 |

- Copies are not spent on upgrades. The owned Spark has the highest regular
  tier whose threshold its current count meets; falling below that threshold
  causes a downgrade. Forbidden remains outside this progression path.
- Losing an absorbed copy below the current tier requirement drops the Spark
  to the previous tier. Unlocked tiers are not permanent.
- Every successful capture awards absorbed copies, including the first capture
  of that Spark.
- The first capture of a species creates its collected Spark at level 1,
  rather than preserving the wild Spark's level. For regular species, the
  owned tier is determined by absorbed-copy count, including the first capture's
  awarded copies; Forbidden species remain Forbidden.
- Rewards are based on the captured Spark's tier:

  | Captured tier | Copies awarded |
  |---|---:|
  | Normal | 1 |
  | Rare | 2 |
  | Legendary | 3 |
  | Royalty | 4 |
  | Ascended | 5 |

- When an NPC player captures the player's Spark, its absorbed-copy count
  decreases by one. Wild Sparks cannot trigger this capture-loss rule.
  NPC collection rewards and inventory remain unspecified.
- A Normal Spark with zero absorbed copies can enter battle.
- If captured while Normal with zero absorbed copies, it remains owned,
  its count stays at zero, and it faints: unavailable for five minutes.
- Capture reducing absorbed copies from one to zero does not cause fainting:
  the last copy absorbs that loss. Capture causes five-minute fainting only
  when the Spark was already at zero copies (Normal or Forbidden).
- Ordinary knockout causes five minutes of fainting for the player's Spark,
  regardless of tier or absorbed-copy count. It remains owned and loses no
  absorbed copies from knockout; battle-related copy loss occurs on capture.
- HP fully recovers after each battle. Fainted Sparks remain unavailable
  for the full five-minute timer and return with full HP when it expires;
  HP recovery does not bypass fainting. Healing items are unnecessary for v1's
  between-battle recovery.
- Temporary buffs, defense effects, and ability cooldowns reset between battles.
  Each encounter starts without effects or cooldowns carried from the previous
  fight. Level, XP, absorbed copies, and collected personalities persist.

### Forbidden

- Forbidden is a separate, strongest tier, outside the regular upgrade path.
- Sparks can only start and remain in Forbidden; regular Sparks cannot
  upgrade into it and Forbidden Sparks cannot downgrade into regular tiers.
- Forbidden Sparks have a maximum level of 50.
- A Forbidden Spark can hold up to 100 absorbed copies. This supersedes the
  earlier interpretation of a one-copy holding limit.
- Each successful Forbidden capture awards one absorbed copy, up to the
  100-copy holding cap. This includes the first capture. The proposed six-copy
  reward was not adopted.
- At the 100-copy cap, further successful Forbidden captures still award one
  personality instance, XP, and Insignia, while the absorbed-copy count stays
  at 100. No extra copy is credited above the cap.
- A Forbidden Spark with zero absorbed copies can enter battle. If captured
  while at zero copies, it remains owned and Forbidden, its count stays at zero,
  and it faints for five minutes, becoming temporarily unavailable.

### Insignia and the shop

- Earned currency is called Insignia.
- Players earn Insignia only when winning a battle or capturing the enemy.
- Initial battle Insignia reward is 10 × enemy level × enemy Spark-tier stat
  multiplier. A level-10 Normal awards 100 Insignia; a level-10 Legendary
  awards 150. Winning and successful capture pay the same Insignia amount.
- Losses and escapes do not award Insignia.
- Successful capture awards both absorbed copies and Insignia.
- Players can buy EMBLEMs and Sparks with Insignia.
- The v1 Spark shop offers all six regular species in the five regular
  tiers, with no stock limit; purchases are constrained by available Insignia.
  Forbidden Sparks are excluded.
- Buying a previously unowned species creates its Spark at level 1. Buying
  additional copies preserves the existing Spark's level.
- Initial EMBLEM shop price is 20% of its strength, in Insignia:

  | EMBLEM tier | Price in Insignia |
  |---|---:|
  | Normal | 20 |
  | Rare | 40 |
  | Legendary | 80 |
  | Royalty | 160 |
  | Ascended | 320 |
  | Forbidden | 640 |

- These prices are initial balance values; Forbidden remains the most expensive
  EMBLEM tier.
- Buying a Spark unlocks its species if unowned, or adds absorbed copies
  to the player's existing Spark of that species. Purchases do not award
  personalities; apart from the starter's one random personality, personalities
  are acquired only through successful captures.
- A newly purchased species without collected personalities can be played
  manually until capture supplies personalities for its autonomous presets.
- Shop purchases grant the same absorbed-copy rewards as captures for regular
  tiers: Normal 1, Rare 2, Legendary 3, Royalty 4, Ascended 5. The purchased tier
  determines the copy reward; the owned regular Spark's tier still follows
  its cumulative copy count. Forbidden Sparks cannot be purchased.
- Players can sell Spark copies for Insignia.
- Each sale removes one absorbed copy. Recalculate tier from the remaining
  count, allowing a regular Spark to downgrade when a threshold is crossed.
- Selling does not cause fainting. A Spark with zero absorbed copies has
  nothing to sell; its owned Spark is not removed by selling copies.
- Sale value depends on Spark base price, tier, and level.
- Initial price for selling one absorbed copy is:

  ```text
  Sale value = species base price × current Spark-tier stat multiplier
               × [1 + 0.05 × (Spark level − 1)]
  ```

- Calculate sale value using the owned Spark's tier and level before removing
  the copy, then round down to whole Insignia. Each level above 1 adds 5% of the
  tier-adjusted base price. Species base prices still need assigning.
- Initial regular-Spark purchase price is:

  ```text
  Purchase price = 2 × copies granted
                   × per-copy sale value at the resulting Spark tier and level
  ```

- Use the owned Spark's resulting tier after adding the purchased copies
  and its level to calculate the per-copy sale value. This keeps purchase cost
  above the immediate resale value of the granted copies, including purchases
  that cross an upgrade threshold. Existing levels are not reset by this pricing
  calculation; a shop-unlocked species starts at level 1.
- Initial species base prices, in Insignia, are:

  | Species role | Base price |
  |---|---:|
  | Guardian | 100 |
  | Striker | 120 |
  | Scout | 110 |
  | Sentinel | 140 |
  | Bruiser | 130 |
  | Channeler | 150 |
  | Forbidden species | 1,000 |

- These base prices feed the sale and purchase formulas. Forbidden's price
  affects sales only because Forbidden Sparks remain capture-only.

## Remaining design questions

### Gameplay and content

- Finalize species identities and ability names. All seven
  initial stat/growth tables, passives, and active ability sets are confirmed.
- Define any personality management/discard flow if needed; there is no gameplay
  storage cap in v1.
- Define species-selection weights within regular and Forbidden encounter pools.

### Engineering details for the eventual specification

- Stat/damage rounding, positive-stat validation, and zero-SPEED handling.
- Enemy-level range clamping when the player's highest level exceeds an enemy's
  cap; exact sampling distribution within the permitted range.
- XP overflow across multiple level-ups and handling at the level cap.
- Randomness and replay behavior, including one authoritative order roll per round.
- Laya situation-question wording, public-state summaries, inference time limits
  and the real-model evaluation. Action weighting is now engine-side (see Action
  policy); EMBLEM fallback to basic ATTACK and the information boundary stay
  confirmed.
- Precise passive trigger timing, defense-rating snapshots, phase ordering,
  and atomic round/terminal-result resolution. A terminal result prevents later
  actions, so simultaneous FLEE ends on the first success and wild CATCH never
  attempts collection.
- Autonomous EMBLEM prompt delivery, deadline enforcement, and late-answer
  handling. The five-second deadline and permitted-tier fallback are confirmed.
- Persistent ownership, copies, currency, XP, inventory, personalities, presets,
  faint expiry, and encounter-roll timestamps use SQLite. Specify transactions,
  ownership isolation, migrations, and recovery of persisted active battles;
  existing mini_games temporary sessions do not provide those guarantees.
- Validation through simulated battles and economy checks before treating
  initial balance numbers as proven.

### Future versions

- NPC-player encounters, NPC inventories and capture rewards, and capture of
  player Sparks. These are outside v1; the agreed player-copy-loss,
  downgrade, and zero-copy faint rules are retained for that later work.

## Decision history and superseded proposals

- Fixed five-copy, same-tier merging was replaced by tier-dependent copy counts.
- SPEED was removed for simultaneous choices, then restored for weighted action
  order while keeping private choices and simultaneous reveal.
- FEAR was initially described as influencing flee success, then corrected to
  influence action preference only. The same rule applies to INTERCEPT.
- INTERCEPT action / CATCH category was renamed to CATCH action / INTERCEPT
  category.
- Defense carrying forward when unused was rejected; expire it each round.
- Fixed 50% base escape chance was replaced by an ESSENCE-dependent base chance.
- Minimum-tier EMBLEM restrictions were rejected in favor of capture strength.
- The original suggested capture-copy rewards 1 / 3 / 8 / 15 / 25 were replaced
  by the user's confirmed 1 / 2 / 3 / 4 / 5 table.
- First-capture unlocking with zero copies was rejected: every capture awards
  its tier's copies, including the first.
- Tier retention after losing copies was rejected: falling below the required
  count causes a downgrade.
- Rewarding losses or escapes was rejected: only wins and captures pay Insignia.
- Ability-specific cooldowns were selected over spending ESSENCE as the mechanism
  for limiting repeated ability use. ESSENCE was subsequently confirmed as a
  power stat that is not consumed.
- Personalities were initially fixed through all progression and duplicate
  collection. This was refined: explicit capture-time replacement is allowed
  for unlocked personalities; automatic personality evolution is still excluded.
- Capture-time selection, personality locks, and skipping replacement when all
  slots were locked were subsequently superseded by a personality pool with one
  random personality awarded per capture and player-created equipped presets.
  Pools were subsequently confirmed as species-specific. The lock mechanism was
  then explicitly removed; each Spark can have up to five presets.
- A highest-tier-only personality pool was briefly selected, then superseded:
  collected personalities are separate entries, including identical type/tier
  duplicates. Presets do not automatically upgrade or replace selected entries
  when a stronger personality is collected.
- Revealing only the awarded personality was initially selected, then replaced:
  successful capture reveals all source personalities, including discarded ones,
  while awarding exactly one instance chosen with equal odds among the source
  Spark's personality instances.
- Forbidden was initially described as holding only one absorbed copy. Its
  holding cap was subsequently changed to 100; distinguish this capacity from
  the earlier one-copy reward instruction.
- Purchase rewards were initially matched to captures for all tiers. Forbidden
  Sparks were then excluded from the shop and made capture-only; regular
  purchase rewards still match regular capture rewards.
- Wild Sparks were initially assumed capable of collecting the player's
  Spark. The user corrected this: only NPC players can capture player
  Sparks. Capture-loss and zero-copy faint rules apply to those NPC captures,
  not collection attempts by wild opponents.
- A single collection entry per species was initially proposed and rejected.
  The user then considered separate same-species individuals with different
  personalities. This was subsequently replaced by one active captured Spark
  per species that absorbs later same-species captures; species-specific
  personality pools and presets provide behavior variation instead.

- 2026-10-10: Laya choosing each action was replaced by an engine-side action
  policy (situation reads from Laya, personality weights, mood draw, repeat
  penalty, seeded sampling) so autonomous Sparks stay varied. The user
  approved this and the mood idea.

## Next planning step

The consolidated backend draft is
[2026-10-10-emberlings-backend-design.md](2026-10-10-emberlings-backend-design.md).
It carries the confirmed rules into an API, storage, round-state, and verification
design, with additional engineering defaults explicitly proposed for review.
Those defaults are not confirmed decisions until the user reviews the draft.

Review that written design, incorporate corrections, then create the backend
implementation plan. Keep this record updated as further decisions are made.
No product implementation has started.
