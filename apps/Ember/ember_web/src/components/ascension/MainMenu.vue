<script setup lang="ts">
import { computed, ref } from "vue";
import { useAscensionStore } from "../../stores/ascension";
import AscendedTemplateCard from "./AscendedTemplateCard.vue";
import EmButton from "./ui/EmButton.vue";
import EmConfirm from "./ui/EmConfirm.vue";
import EmDialog from "./ui/EmDialog.vue";
import EmIcon from "./ui/EmIcon.vue";
import EmMenuRow from "./ui/EmMenuRow.vue";
import EmNotice from "./ui/EmNotice.vue";

/** The Ascension main menu, the first screen: the title, the menu rows and a fanned
 * hand of small cards. Without a save it offers New game and previews the starters;
 * with one it offers Continue, Quick battle and Shop and shows your first Ascended.
 * Reset progress lives here, behind a type-to-confirm. */
export type PlayTarget = "collection" | "battle" | "shop";
const emit = defineEmits<{ newGame: []; play: [target: PlayTarget] }>();

const HAND_SIZE = 3;

const store = useAscensionStore();
const hasSave = computed(() => store.profile !== null);
const inBattle = computed(() => store.profile?.active_battle != null || store.battle?.status === "active");
const confirmingReset = ref(false);
const showingHelp = ref(false);

/** The Ascended of the hand: your first ones (level, tier), or the starters to pick from.
 * `rot` and `lift` place a card in the fan, the middle one raised and on top. */
const hand = computed(() => {
  const catalog = store.catalog?.ascendeds ?? [];
  const entries =
    store.profile !== null
      ? store.profile.ascendeds.slice(0, HAND_SIZE).map((s) => ({
          id: s.ascended_id,
          info: catalog.find((c) => c.id === s.ascended_id),
          level: s.level,
          tierId: s.tier_id,
        }))
      : catalog
          .filter((c) => c.starter)
          .slice(0, HAND_SIZE)
          .map((c) => ({ id: c.id, info: c, level: 1, tierId: "common" }));
  return entries.flatMap((e, i) => {
    if (e.info === undefined) return [];
    const offset = i - (entries.length - 1) / 2;
    return [{ ...e, info: e.info, rot: `${offset * 11}deg`, lift: `${-25 + Math.abs(offset) * 25}px`, z: 10 - Math.round(Math.abs(offset) * 4) }];
  });
});
const handCaption = computed(() => (hasSave.value ? "Your first Ascended" : hand.value.map((h) => h.info.name).join(" · ")));
const ascendedCount = computed(() => store.profile?.ascendeds.length ?? 0);

async function reset(): Promise<void> {
  if (await store.resetProgress()) confirmingReset.value = false;
}
</script>

<template>
  <section class="hero">
    <div class="intro">
      <p class="em-eyebrow">A little fire. A big adventure.</p>
      <h2 class="em-pixel title">ASCENSION</h2>
      <p class="tagline">Find your Ascended.<br />Forge a legend, one battle at a time.</p>
      <p v-if="hasSave" class="save em-num">{{ ascendedCount }} Ascended, {{ store.profile?.insignia }} Insignia</p>
      <p v-else class="save">Three Ascended. Your first choice.</p>

      <EmNotice v-if="store.error" tone="error">{{ store.error }}</EmNotice>

      <nav class="menu" aria-label="Main menu">
        <template v-if="hasSave">
          <EmMenuRow icon="play" variant="primary" @click="emit('play', 'collection')">Continue</EmMenuRow>
          <EmMenuRow icon="battle" @click="emit('play', 'battle')">Quick battle</EmMenuRow>
          <EmMenuRow icon="shop" @click="emit('play', 'shop')">Shop</EmMenuRow>
        </template>
        <EmMenuRow v-else icon="play" variant="primary" @click="emit('newGame')">New game</EmMenuRow>
        <EmMenuRow icon="book" @click="showingHelp = true">How to play</EmMenuRow>
        <EmMenuRow v-if="hasSave" icon="reset" variant="danger" :disabled="inBattle" @click="confirmingReset = true">Reset progress</EmMenuRow>
      </nav>
      <p v-if="hasSave && inBattle" class="caption">Finish or forfeit your battle to reset.</p>
      <p v-else class="caption">{{ hasSave ? "Your progress is ready." : "Pick a starter and begin your collection." }}</p>
    </div>

    <div class="hand-wrap">
      <ul class="hand" :aria-label="hasSave ? 'Your first Ascended' : 'Starter Ascended'">
        <li v-for="ascended in hand" :key="ascended.id" class="ascended" :style="{ '--rot': ascended.rot, '--lift': ascended.lift, zIndex: ascended.z }">
          <AscendedTemplateCard :ascended="ascended.info" :level="ascended.level" :tier-id="ascended.tierId" compact :show-level="hasSave" />
        </li>
      </ul>
      <p class="hand-caption">{{ handCaption }}</p>
    </div>

    <EmConfirm
      :open="confirmingReset"
      title="Reset all Ascension progress?"
      message="You will start again with a new starter Ascended."
      confirm-label="Reset progress"
      cancel-label="Keep my progress"
      danger
      require-text="RESET"
      :busy="store.busy"
      @confirm="reset"
      @close="confirmingReset = false"
    >
      <EmNotice tone="error" class="reset-notice">This permanently removes your Ascended, Insignia, EMBLEMs and presets.</EmNotice>
    </EmConfirm>

    <EmDialog :open="showingHelp" title="Keep the fire going" @close="showingHelp = false">
      <ol class="rules">
        <li><strong>Choose a starter.</strong> Guardian, Scout or Striker begins your collection.</li>
        <li><strong>Find a wild Ascended.</strong> Preview it, then fight or decline for free.</li>
        <li><strong>Make your move.</strong> Play manually or let your Ascended act autonomously.</li>
        <li><strong>Throw an EMBLEM.</strong> Choose a permitted tier before the five-second timer ends.</li>
        <li><strong>Forge your collection.</strong> Earn XP and Insignia; copies raise tiers. Levels cap at 30, or 50 for Forbidden.</li>
      </ol>
      <EmButton variant="primary" class="ready" @click="showingHelp = false"><EmIcon name="play" /> Ready to play</EmButton>
    </EmDialog>
  </section>
</template>

<style scoped>
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  align-items: center;
  gap: 40px;
  min-height: 590px;
  background: radial-gradient(ellipse at 73% 50%, #2a3033, transparent 60%);
}
.title {
  margin: 14px 0;
  font-size: 46px;
  line-height: 1.2;
  color: var(--em-accent);
}
.tagline {
  max-width: 370px;
  margin-bottom: 28px;
  font-size: 16px;
  color: var(--em-muted);
}
.save {
  margin: 0 0 16px;
  font-size: 13px;
}
.menu {
  display: grid;
  gap: 10px;
  max-width: 380px;
  margin-top: 22px;
}
.caption {
  margin-top: 18px;
  font-size: 12px;
  color: var(--em-muted);
}
.hand-wrap {
  min-width: 0;
}
.hand {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 390px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.ascended {
  --card-width: 170px;
  flex: none;
  margin: 0 -12px;
  transform: rotate(var(--rot)) translateY(var(--lift));
  box-shadow: 0 20px 35px #0008;
  transition: transform 160ms ease;
}
.ascended:hover {
  z-index: 20 !important;
  transform: rotate(0deg) translateY(-30px);
}
.hand-caption {
  text-align: center;
  font-size: 11px;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: var(--em-muted);
}
.reset-notice {
  margin-bottom: 18px;
}
.rules {
  margin: 0 0 20px;
  padding-left: 22px;
  color: var(--em-muted);
}
.rules li {
  padding: 8px 0;
}
.rules strong {
  color: var(--em-text);
}
.ready {
  width: 100%;
}
@media (max-width: 700px) {
  .hero {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 26px;
    min-height: 0;
  }
  .title {
    margin: 12px 0;
    font-size: 31px;
  }
  .tagline {
    margin-bottom: 16px;
    font-size: 14px;
  }
  .menu {
    max-width: none;
  }
  .hand-wrap {
    order: 2;
  }
  .hand {
    height: 270px;
  }
  .ascended {
    --card-width: 128px;
    margin: 0 -16px;
  }
}
</style>
