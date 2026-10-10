import type { Account } from "./AuthClient";
import type { BattleView, Catalog, EncounterPreview, Fighter, OwnedSpark, Profile, SparkInfo, TierInfo } from "./EmberlingsClient";

/** Test data shaped like mini_games' answers, for the Emberlings tests. */

const nameOf = (id: string) => id.charAt(0).toUpperCase() + id.slice(1);

export function tier(id: string, emblemPrice: number, copyThreshold: number | null): TierInfo {
  return { id, stat_multiplier: 1, copy_threshold: copyThreshold, copy_reward: 1, emblem_strength: 1, emblem_price: emblemPrice };
}

export function sparkInfo(id: string, extra: Partial<SparkInfo> = {}): SparkInfo {
  return {
    id,
    name: nameOf(id),
    starter: false,
    forbidden: false,
    base: { hp: 100, essence: 10, speed: 10 },
    growth: { hp: 5, essence: 1, speed: 1 },
    base_price: 50,
    passive: { kind: "steady", params: {} },
    abilities: [
      { id: `${id}_strike`, name: "Strike", unlock_level: 1, category: "ATTACK", percentage: 120, cooldown: 1, stat: null, duration: null },
      { id: `${id}_rally`, name: "Rally", unlock_level: 5, category: "SUPPORT", percentage: 50, cooldown: 3, stat: "essence", duration: 2 },
    ],
    ...extra,
  };
}

export const CATALOG: Catalog = {
  version: 1,
  tiers: [
    tier("common", 10, 0),
    tier("rare", 40, 3),
    tier("unique", 90, 6),
    tier("royal", 150, 10),
    tier("legendary", 250, 15),
    tier("forbidden", 500, null),
  ],
  levels: { regular_cap: 30, forbidden_cap: 50 },
  sparks: [
    sparkInfo("guardian", { starter: true }),
    sparkInfo("striker", { starter: true }),
    sparkInfo("bruiser"),
    sparkInfo("forbidden", { forbidden: true }),
  ],
  personalities: [
    { id: "AGGRESSIVE", categories: ["ATTACK"] },
    { id: "CAUTIOUS", categories: ["DEFENSE"] },
  ],
};

export function ownedSpark(id: string, extra: Partial<OwnedSpark> = {}): OwnedSpark {
  return {
    spark_id: id,
    name: nameOf(id),
    level: 3,
    xp: 40,
    xp_needed: 300,
    level_cap: 30,
    copies: 1,
    tier_id: "common",
    faint_until: null,
    fainted: false,
    ...extra,
  };
}

export const PROFILE: Profile = {
  owner: "1",
  insignia: 100,
  emblems: { common: 2 },
  sparks: [ownedSpark("guardian")],
  pending_encounter: null,
  active_battle: null,
  next_roll_at: null,
};

export const ENCOUNTER: EncounterPreview = {
  id: "e1",
  spark_id: "bruiser",
  name: "Bruiser",
  tier_id: "rare",
  level: 4,
  status: "pending",
  created_at: 1_700_000_000,
};

export function fighter(sparkId: string, extra: Partial<Fighter> = {}): Fighter {
  return {
    spark_id: sparkId,
    name: nameOf(sparkId),
    tier_id: "common",
    level: 3,
    hp: 80,
    max_hp: 100,
    essence: 12,
    speed: 9,
    buffs: [],
    defense: null,
    abilities: [{ id: `${sparkId}_strike`, name: "Strike", category: "ATTACK", percentage: 120, cooldown: 1, ready: true }],
    ...extra,
  };
}

export function battleView(extra: Partial<BattleView> = {}): BattleView {
  return {
    id: "b1",
    status: "active",
    phase: "choosing",
    mode: "autonomous",
    round: 1,
    revision: 1,
    emblem_limit: "common",
    player: fighter("guardian"),
    wild: fighter("bruiser"),
    actions: [
      { kind: "attack", category: "ATTACK", ability_id: null, name: null, percentage: 100 },
      { kind: "ability", category: "ATTACK", ability_id: "guardian_strike", name: "Strike", percentage: 120 },
      { kind: "flee", category: "FEAR", ability_id: null, name: null, percentage: 100 },
      { kind: "catch", category: "INTERCEPT", ability_id: null, name: null, percentage: 100 },
    ],
    emblems: { common: 2 },
    prompt: null,
    history: [],
    result: null,
    ...extra,
  };
}

export const ACCOUNT_WITH_EMBERLINGS: Account = {
  id: 1,
  username: "lex",
  email: "lex@example.com",
  email_verified: true,
  roles: [],
  permissions: ["chat.use", "emberlings.play"],
};
