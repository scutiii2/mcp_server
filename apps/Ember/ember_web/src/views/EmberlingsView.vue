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
import MainMenu, { type PlayTarget } from "../components/emberlings/MainMenu.vue";
import ShopPanel from "../components/emberlings/ShopPanel.vue";
import StarterPick from "../components/emberlings/StarterPick.vue";
import { useEmberlingsStore } from "../stores/emberlings";
import { titleCase } from "../utils/emberlings";

/** Emberlings: a main menu, then collect Sparks, battle wild ones, spend Insignia. App.vue keeps
 * this page alive across tab switches, so an open battle survives; the store's
 * loop runs only while the page is attached and the browser tab is visible. */
type Tab = PlayTarget;
type Screen = "menu" | "starter" | "game";

const store = useEmberlingsStore();
const screen = ref<Screen>("menu");
const tab = ref<Tab>("collection");
const tabs: { value: Tab; label: string }[] = [
  { value: "collection", label: "Collection" },
  { value: "battle", label: "Battle" },
  { value: "shop", label: "Shop" },
];
const emblemSummary = computed(() => {
  const owned = store.profile?.emblems ?? {};
  const parts = (store.catalog?.tiers ?? [])
    .filter((t) => (owned[t.id] ?? 0) > 0)
    .map((t) => `${titleCase(t.id)} ${owned[t.id] ?? 0}`);
  return parts.length > 0 ? parts.join(" · ") : "none";
});

function play(target: PlayTarget): void {
  tab.value = target;
  screen.value = "game";
}

// A restored (or just started) battle, or an encounter, skips the menu: an
// open battle must not run unseen behind it.
watch(
  () => store.battle?.id ?? store.encounter?.id ?? null,
  (id) => {
    if (id !== null) play("battle");
  },
  { immediate: true },
);
// Losing the save (reset) sends the page back to the menu.
watch(
  () => store.needsStarter,
  (needs) => {
    if (needs) screen.value = "menu";
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
      <div v-if="screen === 'game' || !store.loaded" class="top">
        <div>
          <h2 class="page-title">Emberlings</h2>
          <p class="page-description">Collect Sparks, battle wild ones and spend Insignia in the shop.</p>
        </div>
        <dl v-if="store.profile && screen === 'game'" class="wallet">
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
        <p v-if="store.reconnecting" class="muted status" role="status">Reconnecting...</p>
        <MainMenu v-if="screen === 'menu'" @new-game="screen = 'starter'" @play="play" />
        <StarterPick v-else-if="screen === 'starter'" @back="screen = 'menu'" @started="play('collection')" />

        <template v-else>
          <div class="game-nav">
            <button type="button" class="chip" @click="screen = 'menu'">Menu</button>
            <SegmentedControl v-model="tab" :options="tabs" aria-label="Emberlings sections" />
          </div>
          <p v-if="store.error" class="error status" role="alert">{{ store.error }}</p>

        <div v-if="tab === 'collection'" class="tab-body">
          <CollectionPanel />
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
.game-nav {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}
</style>
