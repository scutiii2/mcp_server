<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from "vue";
import "../components/infoPage.css";
import "../components/emberlings/fonts";
import "../components/emberlings/theme.css";
import ActionBar from "../components/emberlings/ActionBar.vue";
import BattleArena from "../components/emberlings/BattleArena.vue";
import BattleResult from "../components/emberlings/BattleResult.vue";
import CollectionPanel from "../components/emberlings/CollectionPanel.vue";
import EmShell from "../components/emberlings/EmShell.vue";
import EmblemPrompt from "../components/emberlings/EmblemPrompt.vue";
import EncounterPanel from "../components/emberlings/EncounterPanel.vue";
import MainMenu, { type PlayTarget } from "../components/emberlings/MainMenu.vue";
import ShopPanel from "../components/emberlings/ShopPanel.vue";
import StarterPick from "../components/emberlings/StarterPick.vue";
import EmIcon from "../components/emberlings/ui/EmIcon.vue";
import EmTabs, { type EmTabOption } from "../components/emberlings/ui/EmTabs.vue";
import { useEmberlingsStore } from "../stores/emberlings";
import { titleCase } from "../utils/emberlings";

/** Emberlings: a main menu, then collect Sparks, battle wild ones, spend Insignia.
 * The page has its own theme (components/emberlings/theme.css). App.vue keeps this
 * page alive across tab switches, so an open battle survives; the store's loop runs
 * only while the page is attached and the browser tab is visible. */
type Tab = PlayTarget;
type Screen = "menu" | "starter" | "game";

const store = useEmberlingsStore();
const screen = ref<Screen>("menu");
const tab = ref<Tab>("collection");
const tabs: EmTabOption[] = [
  { value: "collection", label: "Collection", icon: "book" },
  { value: "battle", label: "Battle", icon: "battle" },
  { value: "shop", label: "Shop", icon: "shop" },
];
const PAGE_TITLES: Record<Tab, { title: string }> = {
  collection: { title: "Your collection" },
  battle: { title: "Into the wild" },
  shop: { title: "The forge shop" },
};
const subtitle = computed(() => {
  if (tab.value === "collection") {
    const n = store.profile?.sparks.length ?? 0;
    return `${n} ${n === 1 ? "Spark" : "Sparks"}. Every one has a story.`;
  }
  const owned = store.profile?.emblems ?? {};
  const parts = (store.catalog?.tiers ?? [])
    .filter((t) => (owned[t.id] ?? 0) > 0)
    .map((t) => `${titleCase(t.id)} ${owned[t.id] ?? 0}`);
  return `EMBLEMs: ${parts.length > 0 ? parts.join(" · ") : "none"}`;
});

function play(target: PlayTarget): void {
  tab.value = target;
  screen.value = "game";
}

function selectTab(value: string): void {
  tab.value = value as Tab;
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
  <section class="info-page em-root emberlings-page">
    <EmShell :insignia="store.profile?.insignia ?? null">
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
          <div class="topline">
            <div>
              <p class="em-eyebrow">The forge is yours</p>
              <h2 class="em-pixel page-title">{{ PAGE_TITLES[tab].title }}</h2>
              <p class="page-sub">{{ subtitle }}</p>
            </div>
            <div class="nav">
              <button type="button" class="menu-link" @click="screen = 'menu'"><EmIcon name="arrow" class="back-arrow" /> Main menu</button>
              <EmTabs :model-value="tab" :options="tabs" aria-label="Emberlings sections" @update:model-value="selectTab" />
            </div>
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
    </EmShell>
  </section>
</template>

<style scoped>
.emberlings-page {
  overflow-y: auto;
}
.topline {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--em-space-4);
}
.page-title {
  margin: 8px 0 4px;
  font-size: 28px;
  line-height: 1.3;
}
.page-sub {
  color: var(--em-muted);
}
.nav {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--em-space-4);
}
.menu-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: var(--em-target);
  padding: 0 4px;
  border: 0;
  color: var(--em-accent);
  background: none;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
.back-arrow {
  transform: scaleX(-1);
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
  margin-top: var(--em-space-5);
}
@media (max-width: 700px) {
  .page-title {
    font-size: 23px;
  }
  .nav {
    width: 100%;
  }
}
</style>
