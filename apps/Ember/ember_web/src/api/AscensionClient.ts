import { apiRequest } from "./http";

/** The Ascension game (apps/mini_games) through ember_api's /api/ascension
 * pass-through. Field names are mini_games' own. Every change carries an
 * Idempotency-Key: a fresh one per user action, unless the caller passes the
 * key of the action it is retrying. Times (`next_roll_at`, `faint_until`,
 * `deadline`, `created_at`) are server epoch seconds. */

export type BattleMode = "manual" | "autonomous";
export type ActionKind = "attack" | "ability" | "flee" | "catch";
export type ResultKind = "won" | "knocked_out" | "captured" | "escaped" | "wild_escaped" | "forfeited";
export type Side = "player" | "wild";

export interface TierInfo {
  id: string;
  stat_multiplier: number;
  /** Copies a regular Ascended needs for this tier; null for the Forbidden tier. */
  copy_threshold: number | null;
  copy_reward: number;
  emblem_strength: number;
  emblem_price: number;
}

export interface AbilityInfo {
  id: string;
  name: string;
  unlock_level: number;
  category: string;
  percentage: number;
  cooldown: number;
  stat: string | null;
  duration: number | null;
}

export interface AscendedInfo {
  id: string;
  name: string;
  starter: boolean;
  forbidden: boolean;
  /** Ascension Type ids; zero or more. */
  ascension_types: string[];
  base: Record<string, number>;
  growth: Record<string, number>;
  base_price: number;
  passive: { kind: string; params: Record<string, unknown> };
  abilities: AbilityInfo[];
}

export interface Catalog {
  version: number;
  /** Weakest first. */
  tiers: TierInfo[];
  levels: { regular_cap: number; forbidden_cap: number };
  ascendeds: AscendedInfo[];
  personalities: { id: string; categories: string[] }[];
}

export interface OwnedAscended {
  ascended_id: string;
  name: string;
  ascension_types: string[];
  level: number;
  xp: number;
  /** null at the level cap. */
  xp_needed: number | null;
  level_cap: number;
  copies: number;
  tier_id: string;
  faint_until: number | null;
  fainted: boolean;
}

export interface Profile {
  owner: string;
  insignia: number;
  emblems: Record<string, number>;
  ascendeds: OwnedAscended[];
  pending_encounter: string | null;
  active_battle: string | null;
  next_roll_at: number | null;
}

export interface PersonalityItem {
  id: string;
  type: string;
  tier: number;
}

export interface PersonalityPage {
  items: PersonalityItem[];
  next_cursor: number | null;
}

export interface Preset {
  ascended_id: string;
  slot: number;
  instance_ids: string[];
}

export interface EncounterPreview {
  id: string;
  ascended_id: string;
  name: string;
  tier_id: string;
  level: number;
  status: string;
  created_at: number;
}

export interface Buff {
  source: string;
  stat: string;
  amount: number;
  /** null: lasts the whole battle. */
  rounds_left: number | null;
}

export interface DefenseEffect {
  rating: number;
  attacks_left: number;
  rounds_left: number;
}

export interface FighterAbility {
  id: string;
  name: string;
  category: string;
  percentage: number;
  cooldown: number;
  ready: boolean;
}

export interface Fighter {
  ascended_id: string;
  name: string;
  tier_id: string;
  level: number;
  hp: number;
  max_hp: number;
  essence: number;
  speed: number;
  buffs: Buff[];
  defense: DefenseEffect | null;
  abilities: FighterAbility[];
}

export interface LegalAction {
  kind: ActionKind;
  category: string;
  ability_id: string | null;
  name: string | null;
  percentage: number;
}

export interface EmblemPromptState {
  /** Server time; the page never uses it (see seconds_left). */
  deadline: number;
  seconds_left: number;
  permitted_tiers: string[];
  owned: Record<string, number>;
}

export interface BattleEvent {
  type: string;
  side?: Side;
  [field: string]: unknown;
}

export interface HistoryRound {
  round: number;
  /** side -> [action key ("attack", "ability:<id>", "flee", "catch"), category] */
  actions: Record<Side, [string, string]>;
  events: BattleEvent[];
}

export interface RevealedPersonality {
  id: string;
  type: string;
  tier: number;
}

export interface BattleResult {
  kind: ResultKind;
  xp?: number;
  insignia?: number;
  level_before?: number;
  level_after?: number;
  ascended_id?: string;
  copies_granted?: number;
  copies?: number;
  tier_id?: string;
  awarded_personality?: RevealedPersonality;
  revealed_personalities?: RevealedPersonality[];
  faint_until?: number;
}

export interface BattleView {
  id: string;
  status: "active" | "terminal";
  phase: "choosing" | "awaiting_emblem" | "terminal";
  mode: BattleMode;
  round: number;
  revision: number;
  emblem_limit: string | null;
  player: Fighter;
  wild: Fighter;
  actions: LegalAction[];
  emblems: Record<string, number>;
  prompt: EmblemPromptState | null;
  history: HistoryRound[];
  result: BattleResult | null;
}

/** The round and revision a round change was based on (a stale pair is a 409). */
export interface RoundRef {
  round: number;
  revision: number;
}

export interface ActionChoice {
  kind: ActionKind;
  ability_id?: string;
  emblem_tier?: string;
}

export interface StartBattleInput {
  encounter_id: string;
  ascended_id: string;
  preset_slot: number | null;
  mode: BattleMode;
  emblem_limit: string | null;
}

export interface EmblemPurchase {
  kind: "emblems";
  tier_id: string;
  quantity: number;
  price: number;
}

export interface CopyPurchase {
  kind: "copies";
  ascended_id: string;
  tier_id: string;
  copies_granted: number;
  price: number;
  resulting_tier_id: string;
}

export interface Sale {
  kind: "sale";
  ascended_id: string;
  value: number;
  copies: number;
  tier_id: string;
  downgraded: boolean;
}

const BASE = "/api/ascension";

/** A new Idempotency-Key for one user action. randomUUID exists only in
 * secure contexts (HTTPS or localhost); getRandomValues works everywhere. */
export function newIdempotencyKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
}

const withKey = (key: string): Record<string, string> => ({ "Idempotency-Key": key });
const part = (id: string): string => encodeURIComponent(id);
const round = (at: RoundRef) => ({ round: at.round, revision: at.revision });

export const ascensionClient = {
  catalog: () => apiRequest<Catalog>("GET", `${BASE}/catalog`),
  /** 404 (ApiError) until the account has chosen a starter. */
  profile: () => apiRequest<Profile>("GET", `${BASE}/profile`),
  createProfile: (starterAscendedId: string, key: string = newIdempotencyKey()) =>
    apiRequest<Profile>("POST", `${BASE}/profile`, { starter_ascended_id: starterAscendedId }, withKey(key)),
  /** Deletes every Ascended, personality, preset, EMBLEM and Insignia. 404: no profile; 409: a battle is active. */
  resetProfile: (key: string = newIdempotencyKey()) =>
    apiRequest<{ reset: boolean }>("POST", `${BASE}/profile/reset`, {}, withKey(key)),
  personalities: (ascendedId: string, cursor: number | null = null, limit?: number) => {
    const query = new URLSearchParams();
    if (limit !== undefined) query.set("limit", String(limit));
    if (cursor !== null) query.set("cursor", String(cursor));
    const text = query.toString();
    return apiRequest<PersonalityPage>("GET", `${BASE}/ascendeds/${part(ascendedId)}/personalities${text ? `?${text}` : ""}`);
  },
  preset: (ascendedId: string, slot: number) => apiRequest<Preset>("GET", `${BASE}/ascendeds/${part(ascendedId)}/presets/${slot}`),
  savePreset: (ascendedId: string, slot: number, instanceIds: string[], key: string = newIdempotencyKey()) =>
    apiRequest<Preset>("PUT", `${BASE}/ascendeds/${part(ascendedId)}/presets/${slot}`, { instance_ids: instanceIds }, withKey(key)),
  rollEncounter: (key: string = newIdempotencyKey()) =>
    apiRequest<EncounterPreview>("POST", `${BASE}/encounters`, undefined, withKey(key)),
  encounter: (id: string) => apiRequest<EncounterPreview>("GET", `${BASE}/encounters/${part(id)}`),
  declineEncounter: (id: string, key: string = newIdempotencyKey()) =>
    apiRequest<EncounterPreview>("POST", `${BASE}/encounters/${part(id)}/decline`, undefined, withKey(key)),
  startBattle: (input: StartBattleInput, key: string = newIdempotencyKey()) =>
    apiRequest<BattleView>("POST", `${BASE}/battles`, input, withKey(key)),
  battle: (id: string) => apiRequest<BattleView>("GET", `${BASE}/battles/${part(id)}`),
  action: (id: string, at: RoundRef, choice: ActionChoice, key: string = newIdempotencyKey()) =>
    apiRequest<BattleView>("POST", `${BASE}/battles/${part(id)}/actions`, { ...round(at), action: choice }, withKey(key)),
  emblem: (id: string, at: RoundRef, tier: string, key: string = newIdempotencyKey()) =>
    apiRequest<BattleView>("POST", `${BASE}/battles/${part(id)}/emblem`, { ...round(at), tier }, withKey(key)),
  advance: (id: string, at: RoundRef, key: string = newIdempotencyKey()) =>
    apiRequest<BattleView>("POST", `${BASE}/battles/${part(id)}/advance`, round(at), withKey(key)),
  /** emblemLimit null keeps the battle's own limit. */
  setMode: (id: string, at: RoundRef, mode: BattleMode, emblemLimit: string | null, key: string = newIdempotencyKey()) =>
    apiRequest<BattleView>(
      "POST",
      `${BASE}/battles/${part(id)}/mode`,
      { ...round(at), mode, ...(emblemLimit === null ? {} : { emblem_limit: emblemLimit }) },
      withKey(key),
    ),
  forfeit: (id: string, key: string = newIdempotencyKey()) =>
    apiRequest<BattleView>("POST", `${BASE}/battles/${part(id)}/forfeit`, undefined, withKey(key)),
  buyEmblems: (tier: string, quantity: number, key: string = newIdempotencyKey()) =>
    apiRequest<EmblemPurchase>("POST", `${BASE}/shop/purchases`, { kind: "emblem", tier, quantity }, withKey(key)),
  buyCopies: (ascendedId: string, tier: string, key: string = newIdempotencyKey()) =>
    apiRequest<CopyPurchase>("POST", `${BASE}/shop/purchases`, { kind: "copies", ascended_id: ascendedId, tier }, withKey(key)),
  sellCopy: (ascendedId: string, key: string = newIdempotencyKey()) =>
    apiRequest<Sale>("POST", `${BASE}/ascendeds/${part(ascendedId)}/sales`, undefined, withKey(key)),
};
