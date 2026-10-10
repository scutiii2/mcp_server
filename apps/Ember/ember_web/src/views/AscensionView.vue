<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from "vue";
import "../components/ascension/fonts";
import "../components/ascension/theme.css";
import ActionBar from "../components/ascension/ActionBar.vue";
import BattleArena from "../components/ascension/BattleArena.vue";
import BattleControls from "../components/ascension/BattleControls.vue";
import BattleResult from "../components/ascension/BattleResult.vue";
import CollectionPanel from "../components/ascension/CollectionPanel.vue";
import EmShell from "../components/ascension/EmShell.vue";
import EmblemPrompt from "../components/ascension/EmblemPrompt.vue";
import EncounterPanel, { type EncounterStage } from "../components/ascension/EncounterPanel.vue";
import RoundLog from "../components/ascension/RoundLog.vue";
import MainMenu, { type PlayTarget } from "../components/ascension/MainMenu.vue";
import ShopPanel from "../components/ascension/ShopPanel.vue";
import StarterPick from "../components/ascension/StarterPick.vue";
import EmButton from "../components/ascension/ui/EmButton.vue";
import EmIcon from "../components/ascension/ui/EmIcon.vue";
import EmNotice from "../components/ascension/ui/EmNotice.vue";
import EmPageHead from "../components/ascension/ui/EmPageHead.vue";
import EmPanel from "../components/ascension/ui/EmPanel.vue";
import EmTabs, { type EmTabOption } from "../components/ascension/ui/EmTabs.vue";
import { useAscensionStore } from "../stores/ascension";
import { titleCase } from "../utils/ascension";

/** Ascension: a main menu, then collect Ascended, battle wild ones, spend Insignia.
 * The page has its own theme (components/ascension/theme.css). App.vue keeps this
 * page alive across tab switches, so an open battle survives; the store's loop runs
 * only while the page is attached and the browser tab is visible. */
type Tab = PlayTarget;
type Screen = "menu" | "starter" | "game";

const store = useAscensionStore();
const screen = ref<Screen>("menu");
const tab = ref<Tab>("collection");
const tabs: EmTabOption[] = [
  { value: "collection", label: "Collection", icon: "book" },
  { value: "battle", label: "Battle", icon: "battle" },
  { value: "shop", label: "Shop", icon: "shop" },
];
const encounterStage = ref<EncounterStage>("look");
/** The page title and the line under it, from the tab and, in Battle, the step. */
const heading = computed<{ title: string; subtitle: string }>(() => {
  if (tab.value === "collection") {
    const n = store.profile?.ascendeds.length ?? 0;
    return { title: "Your collection", subtitle: `${n} Ascended. Every one has a story.` };
  }
  if (tab.value === "shop") return { title: "The forge shop", subtitle: "A little preparation goes a long way." };
  const battle = store.battle;
  if (battle !== null) {
    if (battle.result) return { title: "Battle complete", subtitle: "A new chapter for your collection." };
    return { title: "The forge arena", subtitle: `${battle.player.name} vs. wild ${battle.wild.name} · Round ${battle.round}` };
  }
  const wild = store.encounter;
  if (encounterStage.value === "setup" && wild !== null) {
    return { title: "Prepare for battle", subtitle: `Wild ${wild.name} · ${titleCase(wild.tier_id)} · Level ${wild.level}` };
  }
  if (encounterStage.value === "preview") return { title: "A wild Ascended appeared", subtitle: "Take a look. Choose your moment." };
  return { title: "Into the wild", subtitle: "Your next Ascended is waiting." };
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
  <section class="em-root ascension-page">
    <EmShell :insignia="store.profile?.insignia ?? 0">
      <EmPanel v-if="store.unavailable" class="state unavailable" role="alert">
        <EmIcon name="warning" :size="40" />
        <h2 class="em-pixel">Ascension is not available right now</h2>
        <p>Try connecting to the forge again.</p>
        <EmButton variant="primary" :disabled="store.loading" @click="store.retry()">Retry</EmButton>
      </EmPanel>

      <EmPanel v-else-if="!store.loaded" class="state loading">
        <EmIcon name="flame" :size="40" />
        <h2 class="em-pixel">Loading your Ascended…</h2>
        <p>Preparing your collection and wallet.</p>
        <EmNotice v-if="store.error" tone="error">Could not load Ascension: {{ store.error }}</EmNotice>
        <EmButton v-if="store.error && !store.loading" @click="store.retry()">Retry</EmButton>
        <div v-else class="skeletons" aria-hidden="true"><span v-for="n in 4" :key="n" class="skeleton" /></div>
      </EmPanel>

      <template v-else>
        <EmNotice v-if="store.reconnecting" class="status">Reconnecting… Your battle will resume when connected.</EmNotice>
        <MainMenu v-if="screen === 'menu'" @new-game="screen = 'starter'" @play="play" />
        <StarterPick v-else-if="screen === 'starter'" @back="screen = 'menu'" @started="play('collection')" />

        <template v-else>
          <EmPageHead :title="heading.title" :subtitle="heading.subtitle">
            <button type="button" class="menu-link" @click="screen = 'menu'"><EmIcon name="arrow" class="back-arrow" /> Main menu</button>
            <EmTabs :model-value="tab" :options="tabs" aria-label="Ascension sections" @update:model-value="selectTab" />
          </EmPageHead>
          <EmNotice v-if="store.error" tone="error" class="status">{{ store.error }}</EmNotice>

          <div v-if="tab === 'collection'" class="tab-body">
            <CollectionPanel />
          </div>

          <div v-else-if="tab === 'battle'" class="tab-body">
            <template v-if="store.battle">
              <BattleResult v-if="store.battle.result" :battle="store.battle" />
              <template v-else>
                <BattleControls :battle="store.battle" />
                <BattleArena :battle="store.battle" />
                <div class="battle-bottom">
                  <ActionBar :battle="store.battle" />
                  <RoundLog :battle="store.battle" />
                </div>
                <EmblemPrompt />
              </template>
            </template>
            <EncounterPanel v-else @stage="encounterStage = $event" />
          </div>

          <ShopPanel v-else class="tab-body" />
        </template>
      </template>
    </EmShell>
  </section>
</template>

<style scoped>
.ascension-page {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
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
.state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--em-space-3);
  padding: 48px 24px;
  text-align: center;
}
.state svg {
  color: var(--em-accent);
}
.state h2 {
  margin: 0;
  font-size: 18px;
  line-height: 1.4;
}
.state p {
  max-width: 360px;
  color: var(--em-muted);
}
.skeletons {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 20px;
  margin-top: var(--em-space-3);
}
.skeleton {
  width: 140px;
  aspect-ratio: 1060 / 1484;
  border: 1px solid var(--em-border);
  background: linear-gradient(var(--em-raised) 25%, #334756 25% 74%, var(--em-raised) 74%);
}
.status {
  margin: var(--em-space-3) 0;
}
.tab-body {
  margin-top: var(--em-space-5);
}
.battle-bottom {
  display: grid;
  grid-template-columns: 1.15fr 1fr;
  gap: var(--em-space-5);
  margin-top: var(--em-space-5);
}
@media (max-width: 700px) {
  .battle-bottom {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--em-space-4);
  }
}
</style>
