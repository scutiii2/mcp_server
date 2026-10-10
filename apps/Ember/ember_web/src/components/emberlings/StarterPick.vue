<script setup lang="ts">
import { computed, ref } from "vue";
import { useEmberlingsStore } from "../../stores/emberlings";
import SparkTemplateCard from "./SparkTemplateCard.vue";

/** New game: pick the first Spark from a list of small cards (the chosen one
 * glows); the big card shows the chosen Spark in full. Back returns to the menu. */
const emit = defineEmits<{ back: []; started: [] }>();

const store = useEmberlingsStore();
const picked = ref<string | null>(null);
const starters = computed(() => (store.catalog?.sparks ?? []).filter((s) => s.starter));
/** The first starter shows until another is chosen, so the big card is never empty. */
const current = computed(() => starters.value.find((s) => s.id === picked.value) ?? starters.value[0] ?? null);

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
    <button type="button" class="back" @click="emit('back')">Back to menu</button>
    <h3>Choose your first Spark</h3>
    <p class="muted">It stays yours. Other Sparks can be caught in battle or bought in the shop later.</p>

    <div v-if="current" class="picker">
      <div class="choices" role="radiogroup" aria-label="Starter Sparks">
        <div
          v-for="s in starters"
          :key="s.id"
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
          <SparkTemplateCard :spark="s" compact />
        </div>
      </div>
      <SparkTemplateCard :spark="current" class="detail" />
    </div>

    <button type="button" class="primary start" :disabled="current === null || store.busy" @click="start">
      {{ current === null ? "No starters available" : `Start with ${current.name}` }}
    </button>
  </section>
</template>

<style scoped>
.starters h3 {
  margin: 12px 0 4px;
}
.back {
  padding: 0;
  border: 0;
  color: var(--muted);
  background: none;
  font: inherit;
  cursor: pointer;
}
.back::before {
  content: "\2190  ";
}
.picker {
  display: flex;
  align-items: flex-start;
  gap: 24px;
  margin-top: 16px;
}
.choices {
  display: flex;
  flex: none;
  flex-direction: column;
  gap: 16px;
}
.choice {
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: filter 0.15s ease;
}
.choice:hover {
  filter: brightness(1.12);
}
.choice:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 4px;
}
/* The glow follows the card's shape, since it is drawn from the card's own pixels. */
.choice.selected {
  filter: drop-shadow(0 0 3px var(--accent)) drop-shadow(0 0 9px var(--accent));
}
.detail {
  flex: none;
}
.start {
  margin-top: 20px;
}
@media (max-width: 760px) {
  .picker {
    flex-direction: column;
  }
  .choices {
    flex-direction: row;
    flex-wrap: wrap;
  }
}
@media (prefers-reduced-motion: reduce) {
  .choice {
    transition: none;
  }
}
</style>
