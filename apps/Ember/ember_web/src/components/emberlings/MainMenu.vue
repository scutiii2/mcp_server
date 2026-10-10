<script setup lang="ts">
import { computed, ref } from "vue";
import { useEmberlingsStore } from "../../stores/emberlings";
import BaseModal from "../BaseModal.vue";
import ConfirmModal from "../ConfirmModal.vue";
import SparkTemplateCard from "./SparkTemplateCard.vue";

/** The Emberlings main menu, the first screen: a title, large menu rows and a
 * Spark showcase. Without a save it offers New game and previews the starters;
 * with one it offers Continue, Quick battle and Shop and shows your team.
 * Reset progress lives here, behind a type-to-confirm. */
export type PlayTarget = "collection" | "battle" | "shop";
const emit = defineEmits<{ newGame: []; play: [target: PlayTarget] }>();

// 24x24 stroke icons, as path data.
const ICON = {
  play: ["M7 4v16l13-8z"],
  swords: ["M14.5 17.5L3 6V3h3l11.5 11.5", "M13 19l6-6", "M16 16l4 4", "M19 21l2-2"],
  shop: ["M3 21h18", "M3 7h18l-2-4H5z", "M5 21V10", "M19 21V10", "M9 21v-5h6v5"],
  book: ["M4 5a8 8 0 0 1 8 1.5A8 8 0 0 1 20 5v13a8 8 0 0 0-8 1.5A8 8 0 0 0 4 18z", "M12 6.5v13"],
  reset: ["M20 11a8 8 0 0 0-15.5-2", "M4 5v4h4", "M4 13a8 8 0 0 0 15.5 2", "M20 19v-4h-4"],
  chevron: ["M9 6l6 6-6 6"],
};
const SHOWCASE_SIZE = 3;

const store = useEmberlingsStore();
const hasSave = computed(() => store.profile !== null);
const inBattle = computed(() => store.profile?.active_battle != null || store.battle?.status === "active");
const confirmingReset = ref(false);
const showingHelp = ref(false);

/** The Sparks beside the menu, as a fanned hand of small cards: your first ones
 * (with level and tier), or the starters to pick from. `rot` and `lift` place a
 * card in the fan, the middle one on top. */
const showcase = computed(() => {
  const catalog = store.catalog?.sparks ?? [];
  const entries =
    store.profile !== null
      ? store.profile.sparks.slice(0, SHOWCASE_SIZE).map((s) => ({
          id: s.spark_id,
          info: catalog.find((c) => c.id === s.spark_id),
          level: s.level,
          tierId: s.tier_id,
        }))
      : catalog
          .filter((c) => c.starter)
          .slice(0, SHOWCASE_SIZE)
          .map((c) => ({ id: c.id, info: c, level: 1, tierId: "normal" }));
  return entries.flatMap((e, i) => {
    if (e.info === undefined) return [];
    const offset = i - (entries.length - 1) / 2;
    return [{ ...e, info: e.info, rot: `${offset * 9}deg`, lift: `${Math.abs(offset) * 12}px`, z: 10 - Math.round(Math.abs(offset) * 2) }];
  });
});
const sparkCount = computed(() => store.profile?.sparks.length ?? 0);

async function reset(): Promise<void> {
  if (await store.resetProgress()) confirmingReset.value = false;
}
</script>

<template>
  <section class="menu">
    <div class="intro">
      <p class="eyebrow">{{ hasSave ? "Welcome back" : "Collect · battle · grow" }}</p>
      <h2 class="title">Emberlings</h2>
      <p class="tagline">
        {{ hasSave ? "Your Sparks are rested and ready." : "Catch Sparks, train them, and take on wild ones." }}
      </p>

      <p v-if="store.error" class="error" role="alert">{{ store.error }}</p>

      <nav class="rows" aria-label="Main menu">
        <template v-if="hasSave">
          <button type="button" class="row primary" @click="emit('play', 'collection')">
            <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in ICON.play" :key="d" :d="d" /></svg>
            <span class="text"><span class="t">Continue</span><span class="d">Open your collection</span></span>
            <svg class="ico go" viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in ICON.chevron" :key="d" :d="d" /></svg>
          </button>
          <button type="button" class="row" @click="emit('play', 'battle')">
            <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in ICON.swords" :key="d" :d="d" /></svg>
            <span class="text"><span class="t">Quick battle</span><span class="d">Find a wild Spark</span></span>
            <svg class="ico go" viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in ICON.chevron" :key="d" :d="d" /></svg>
          </button>
          <button type="button" class="row" @click="emit('play', 'shop')">
            <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in ICON.shop" :key="d" :d="d" /></svg>
            <span class="text"><span class="t">Shop</span><span class="d">Spend your Insignia</span></span>
            <svg class="ico go" viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in ICON.chevron" :key="d" :d="d" /></svg>
          </button>
        </template>
        <button v-else type="button" class="row primary" @click="emit('newGame')">
          <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in ICON.play" :key="d" :d="d" /></svg>
          <span class="text"><span class="t">New game</span><span class="d">Choose your first Spark</span></span>
          <svg class="ico go" viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in ICON.chevron" :key="d" :d="d" /></svg>
        </button>

        <div :class="hasSave ? 'pair' : 'single'">
          <button type="button" class="row" @click="showingHelp = true">
            <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in ICON.book" :key="d" :d="d" /></svg>
            <span class="text"><span class="t">How to play</span><span v-if="!hasSave" class="d">Two minutes to learn</span></span>
            <svg v-if="!hasSave" class="ico go" viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in ICON.chevron" :key="d" :d="d" /></svg>
          </button>
          <button v-if="hasSave" type="button" class="row danger" :disabled="inBattle" @click="confirmingReset = true">
            <svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in ICON.reset" :key="d" :d="d" /></svg>
            <span class="text"><span class="t">Reset progress</span></span>
          </button>
        </div>
      </nav>
      <p v-if="hasSave && inBattle" class="muted note">Finish or forfeit your battle to reset</p>
    </div>

    <aside class="side" :aria-label="hasSave ? 'Your team' : 'Starter Sparks'">
      <p v-if="hasSave" class="muted side-title">Your team</p>
      <ul class="hand">
        <li
          v-for="spark in showcase"
          :key="spark.id"
          class="spark"
          :style="{ '--rot': spark.rot, '--lift': spark.lift, zIndex: spark.z }"
        >
          <SparkTemplateCard :spark="spark.info" :level="spark.level" :tier-id="spark.tierId" compact :show-level="hasSave" />
        </li>
      </ul>
      <p v-if="hasSave" class="muted stats">
        <span><b>{{ sparkCount }}</b> {{ sparkCount === 1 ? "Spark" : "Sparks" }}</span>
        <span><b>{{ store.profile?.insignia }}</b> Insignia</span>
      </p>
      <p v-else class="muted stats">No save found for this account</p>
    </aside>

    <ConfirmModal
      :open="confirmingReset"
      title="Reset all Emberlings progress?"
      message="Every Spark, personality, preset, EMBLEM and all Insignia are deleted. This cannot be undone."
      confirm-label="Reset progress"
      danger
      require-text="RESET"
      :busy="store.busy"
      @confirm="reset"
      @close="confirmingReset = false"
    />

    <BaseModal :open="showingHelp" title="How to play" @close="showingHelp = false">
      <ul class="help">
        <li>Pick a first Spark. It stays yours.</li>
        <li>Battle wild Sparks to win Insignia and catch new ones.</li>
        <li>In a manual battle, choose each action. In autonomous mode your Spark acts on its own.</li>
        <li>An EMBLEM prompt gives you 5 seconds to answer.</li>
        <li>Spend Insignia in the shop.</li>
      </ul>
    </BaseModal>
  </section>
</template>

<style scoped>
.menu {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
  gap: 32px;
  align-items: center;
  padding: 24px 0;
}
.eyebrow {
  margin: 0 0 6px;
  font-size: 0.75rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--accent);
}
.title {
  margin: 0;
  font-size: 2.5rem;
  font-weight: 600;
  line-height: 1.1;
}
.tagline {
  margin: 8px 0 22px;
  color: var(--muted);
  line-height: 1.5;
}
.rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.row {
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text);
  background: var(--surface);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.row:hover:not(:disabled) {
  border-color: var(--accent);
}
.row:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.row:disabled {
  cursor: default;
  opacity: 0.5;
}
.row.primary {
  border-color: var(--accent);
  color: var(--accent-contrast);
  background: var(--accent);
}
.ico {
  flex: none;
  width: 22px;
  height: 22px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
  color: var(--muted);
}
.row.primary .ico {
  color: inherit;
}
.ico.go {
  width: 18px;
  height: 18px;
  margin-left: auto;
}
.text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.t {
  font-weight: 600;
}
.d {
  font-size: 0.8rem;
  color: var(--muted);
}
.row.primary .d {
  color: inherit;
  opacity: 0.85;
}
.danger,
.danger .ico {
  color: var(--danger);
}
.pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.note {
  margin: 8px 0 0;
  font-size: 0.85em;
}
.side-title {
  margin: 0 0 8px;
  font-size: 0.85em;
}
.hand {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  min-height: 220px;
  margin: 0;
  padding: 16px 0 28px;
  list-style: none;
}
.spark {
  --card-width: 150px;
  flex: none;
  margin: 0 -14px;
  transform: rotate(var(--rot)) translateY(var(--lift));
  transition: transform 0.15s ease;
}
.spark:hover {
  z-index: 20 !important;
  transform: rotate(0deg) translateY(-14px);
}
.stats {
  display: flex;
  gap: 18px;
  margin: 16px 0 0;
  font-size: 0.85em;
}
.stats b {
  color: var(--text);
  font-weight: 600;
}
.help {
  margin: 0;
  padding-left: 18px;
  line-height: 1.6;
}
@media (max-width: 640px) {
  .menu {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (prefers-reduced-motion: reduce) {
  .row,
  .spark {
    transition: none;
  }
}
</style>
