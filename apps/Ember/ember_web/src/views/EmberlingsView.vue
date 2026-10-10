<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from "vue";
import "../components/infoPage.css";
import SegmentedControl from "../components/SegmentedControl.vue";
import ActionBar from "../components/emberlings/ActionBar.vue";
import BattleArena from "../components/emberlings/BattleArena.vue";
import BattleResult from "../components/emberlings/BattleResult.vue";
import CollectionPanel from "../components/emberlings/CollectionPanel.vue";
import EmblemPrompt from "../components/emberlings/EmblemPrompt.vue";
import EncounterPanel from "../components/emberlings/EncounterPanel.vue";
import ShopPanel from "../components/emberlings/ShopPanel.vue";
import { useEmberlingsStore } from "../stores/emberlings";
import { titleCase } from "../utils/emberlings";

/** Emberlings: collect Sparks, battle wild ones, spend Insignia. App.vue keeps
 * this page alive across tab switches, so an open battle survives; the store's
 * loop runs only while the page is attached and the browser tab is visible. */
type Tab = "collection" | "battle" | "shop";

const store = useEmberlingsStore();
const tab = ref<Tab>("collection");
const tabs = computed<{ value: Tab; label: string; disabled?: boolean }[]>(() => [
  { value: "collection", label: "Collection" },
  { value: "battle", label: "Battle", disabled: store.needsStarter },
  { value: "shop", label: "Shop", disabled: store.needsStarter },
]);
const starters = computed(() => (store.catalog?.sparks ?? []).filter((s) => s.starter));
const emblemSummary = computed(() => {
  const owned = store.profile?.emblems ?? {};
  const parts = (store.catalog?.tiers ?? [])
    .filter((t) => (owned[t.id] ?? 0) > 0)
    .map((t) => `${titleCase(t.id)} ${owned[t.id] ?? 0}`);
  return parts.length > 0 ? parts.join(" · ") : "none";
});

// A restored (or just started) battle, or an encounter, opens the Battle tab.
watch(
  () => store.battle?.id ?? store.encounter?.id ?? null,
  (id) => {
    if (id !== null) tab.value = "battle";
  },
  { immediate: true },
);
// Without a profile only the Collection tab (the starter pick) is open.
watch(
  () => store.needsStarter,
  (needs) => {
    if (needs) tab.value = "collection";
  },
);

onMounted(() => store.attach());
onActivated(() => store.attach());
onDeactivated(() => store.detach());
onUnmounted(() => store.detach());
</script>

<template>
  <section class="info-page emberlings-page">
    <div class="column page-column">
      <div class="top">
        <div>
          <h2 class="page-title">Emberlings</h2>
          <p class="page-description">Collect Sparks, battle wild ones and spend Insignia in the shop.</p>
        </div>
        <dl v-if="store.profile" class="wallet">
          <div>
            <dt>Insignia</dt>
            <dd>{{ store.profile.insignia }}</dd>
          </div>
          <div>
            <dt>EMBLEMs</dt>
            <dd>{{ emblemSummary }}</dd>
          </div>
        </dl>
      </div>

      <div v-if="store.unavailable" class="card unavailable" role="alert">
        <p>Emberlings is not available right now.</p>
        <button type="button" class="primary" :disabled="store.loading" @click="store.retry()">Retry</button>
      </div>

      <div v-else-if="!store.loaded" class="loading">
        <p v-if="store.error" class="error" role="alert">Could not load Emberlings: {{ store.error }}</p>
        <p v-else class="muted">Loading …</p>
        <button v-if="store.error && !store.loading" type="button" class="chip" @click="store.retry()">Retry</button>
      </div>

      <template v-else>
        <SegmentedControl v-model="tab" :options="tabs" aria-label="Emberlings sections" />
        <p v-if="store.reconnecting" class="muted status" role="status">Reconnecting...</p>
        <p v-if="store.error" class="error status" role="alert">{{ store.error }}</p>

        <div v-if="tab === 'collection'" class="tab-body">
          <section v-if="store.needsStarter" class="starters">
            <h3>Choose your first Spark</h3>
            <p class="muted">It stays yours. Other Sparks can be caught in battle or bought in the shop later.</p>
            <div class="starter-grid">
              <button
                v-for="s in starters"
                :key="s.id"
                type="button"
                class="starter"
                :disabled="store.busy"
                @click="store.createProfile(s.id)"
              >
                <span class="starter-name">{{ s.name }}</span>
                <span class="muted">{{ s.abilities.length }} abilities · passive: {{ titleCase(s.passive.kind) }}</span>
              </button>
            </div>
          </section>
          <CollectionPanel v-else />
        </div>

        <div v-else-if="tab === 'battle'" class="tab-body">
          <template v-if="store.battle">
            <BattleResult v-if="store.battle.result" :battle="store.battle" />
            <BattleArena :battle="store.battle" />
            <template v-if="!store.battle.result">
              <ActionBar :battle="store.battle" />
              <EmblemPrompt />
            </template>
          </template>
          <EncounterPanel v-else />
        </div>

        <ShopPanel v-else class="tab-body" />
      </template>
    </div>
  </section>
</template>

<style scoped>
.top {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.wallet {
  display: flex;
  gap: 16px;
  margin: 0;
}
.wallet div {
  display: flex;
  flex-direction: column;
}
.wallet dt {
  font-size: 0.8em;
  color: var(--muted);
}
.wallet dd {
  margin: 0;
  font-weight: 600;
}
.unavailable {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.unavailable p {
  margin: 0;
}
.status {
  margin: 10px 0 0;
}
.tab-body {
  margin-top: 16px;
}
.starters h3 {
  margin: 0 0 4px;
}
.starter-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.starter {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text);
  background: var(--surface);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.starter:hover:not(:disabled) {
  border-color: var(--accent);
}
.starter:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.starter-name {
  font-weight: 600;
}
@media (prefers-reduced-motion: reduce) {
  .starter {
    transition: none;
  }
}
</style>
