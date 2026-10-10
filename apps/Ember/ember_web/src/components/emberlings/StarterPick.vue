<script setup lang="ts">
import { computed, ref } from "vue";
import { useEmberlingsStore } from "../../stores/emberlings";
import { abilityEffect } from "../../utils/emberlings";
import AscendedTemplateCard from "./AscendedTemplateCard.vue";
import { starterCopy } from "./starterCopy";
import EmButton from "./ui/EmButton.vue";
import EmIcon from "./ui/EmIcon.vue";
import EmPageHead from "./ui/EmPageHead.vue";
import EmPanel from "./ui/EmPanel.vue";
import type { IconName } from "./ui/icons";

/** New game: pick the first Ascended from a column of small cards (the chosen one has the
 * copper outline and says "Selected"); the large card and a side panel show the chosen
 * Ascended in full. The first starter is chosen on open. "Main menu" goes back. */
const emit = defineEmits<{ back: []; started: [] }>();

const CATEGORY_ICONS: Record<string, IconName> = { ATTACK: "sword", DEFENSE: "shield", SUPPORT: "arrow", FLEE: "arrow", INTERCEPT: "ascended" };

const store = useEmberlingsStore();
const picked = ref<string | null>(null);
const starters = computed(() => (store.catalog?.ascendeds ?? []).filter((s) => s.starter));
/** The first starter shows until another is chosen, so the big card is never empty. */
const current = computed(() => starters.value.find((s) => s.id === picked.value) ?? starters.value[0] ?? null);
const copy = computed(() => starterCopy(current.value?.id ?? ""));
const hp = computed(() => ({ base: current.value?.base.hp ?? 0, growth: current.value?.growth.hp ?? 0 }));
const firstAbility = computed(() => current.value?.abilities[0] ?? null);
const unlockLevels = computed(() => (current.value?.abilities ?? []).map((a) => a.unlock_level));

function unlockText(levels: number[]): string {
  if (levels.length === 0) return "";
  const head = levels.slice(0, -1).join(", ");
  return levels.length === 1 ? `${levels[0]}` : `${head} and ${levels[levels.length - 1]}`;
}

function pick(id: string): void {
  if (!store.busy) picked.value = id;
}

async function start(): Promise<void> {
  if (current.value === null) return;
  if ((await store.createProfile(current.value.id)) !== null) emit("started");
}
</script>

<template>
  <section class="starters">
    <EmPageHead title="Choose your first Ascended" subtitle="One companion. A whole world of possibilities.">
      <button type="button" class="back" @click="emit('back')"><EmIcon name="arrow" class="back-arrow" /> Main menu</button>
    </EmPageHead>

    <div v-if="current" class="picker">
      <div class="choices" role="radiogroup" aria-label="Starter Ascended">
        <div v-for="s in starters" :key="s.id" class="item">
          <div
            class="choice"
            :class="{ selected: current.id === s.id }"
            role="radio"
            tabindex="0"
            :aria-checked="current.id === s.id"
            :aria-label="s.name"
            @click="pick(s.id)"
            @keydown.enter.prevent="pick(s.id)"
            @keydown.space.prevent="pick(s.id)"
          >
            <AscendedTemplateCard :ascended="s" compact />
          </div>
          <p class="note">
            <span v-if="current.id === s.id" class="selected-label"><EmIcon name="check" :size="14" /> Selected</span>
            {{ starterCopy(s.id).motto }}
          </p>
        </div>
      </div>

      <AscendedTemplateCard :ascended="current" class="detail" />

      <EmPanel class="info">
        <p class="em-eyebrow">Your chosen starter</p>
        <h3 class="em-pixel name">{{ current.name }}</h3>
        <p class="blurb">{{ copy.blurb }}</p>
        <div class="facts">
          <div>
            <strong><EmIcon name="heart" /> Health</strong>
            <p class="em-num">{{ hp.base }} HP · +{{ hp.growth }} / lvl</p>
          </div>
          <div v-if="firstAbility">
            <strong><EmIcon :name="CATEGORY_ICONS[firstAbility.category] ?? 'ascended'" /> {{ firstAbility.name }}</strong>
            <p>{{ abilityEffect(firstAbility) }}</p>
          </div>
          <div>
            <strong><EmIcon name="flame" /> Grow together</strong>
            <p>Abilities unlock at levels {{ unlockText(unlockLevels) }}.</p>
          </div>
        </div>
        <EmButton variant="primary" class="start" :disabled="store.busy" @click="start">
          <EmIcon name="play" /> Start with {{ current.name }}
        </EmButton>
        <button type="button" class="back-link" @click="emit('back')"><EmIcon name="arrow" class="back-arrow" /> Back to main menu</button>
      </EmPanel>
    </div>
    <p v-else class="empty">No starters available.</p>
  </section>
</template>

<style scoped>
.back,
.back-link {
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
.picker {
  display: grid;
  grid-template-columns: 190px 440px minmax(0, 1fr);
  gap: var(--em-space-6);
  align-items: start;
}
.choices {
  display: flex;
  flex-direction: column;
  gap: 22px;
}
.item {
  --card-width: 170px;
}
.choice {
  width: var(--card-width);
  border-radius: var(--em-radius);
  cursor: pointer;
  transition: box-shadow 160ms ease;
}
.choice:hover {
  filter: brightness(1.1);
}
.choice:focus-visible {
  outline: 2px solid var(--em-accent);
  outline-offset: 3px;
}
.choice.selected {
  outline: 2px solid var(--em-accent);
  outline-offset: 3px;
  box-shadow:
    0 0 0 6px #f3b47a22,
    0 0 24px #f3b47a33;
}
.note {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--em-muted);
}
.selected-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: 700;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: var(--em-accent);
}
.name {
  margin: 16px 0 12px;
  font-size: 18px;
  line-height: 1.4;
}
.blurb {
  color: var(--em-muted);
}
.facts {
  display: grid;
  gap: 18px;
  margin: 24px 0;
}
.facts > div {
  padding-bottom: 14px;
  border-bottom: 1px solid var(--em-divider);
}
.facts strong {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 3px;
  font-size: 16px;
}
.facts p {
  color: var(--em-muted);
}
.start {
  width: 100%;
}
.back-link {
  margin-top: 12px;
}
.empty {
  color: var(--em-muted);
}
@media (max-width: 1100px) {
  .picker {
    grid-template-columns: 190px minmax(0, 1fr);
  }
  .info {
    grid-column: 1 / -1;
  }
}
@media (max-width: 700px) {
  .picker {
    display: flex;
    flex-direction: column;
    gap: 28px;
  }
  .choices {
    width: 100%;
    gap: 18px;
  }
  .item {
    display: flex;
    align-items: center;
    gap: 16px;
    --card-width: 150px;
  }
  .note {
    margin-top: 0;
  }
  .detail {
    --card-width: min(440px, 100%);
    align-self: center;
  }
}
@media (prefers-reduced-motion: reduce) {
  .choice {
    transition: none;
  }
}
</style>
