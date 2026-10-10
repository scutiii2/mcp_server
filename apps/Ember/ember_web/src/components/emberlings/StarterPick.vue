<script setup lang="ts">
import { computed, ref } from "vue";
import { useEmberlingsStore } from "../../stores/emberlings";
import { titleCase } from "../../utils/emberlings";

/** New game: pick the first Spark, then start. Back returns to the menu. */
const emit = defineEmits<{ back: []; started: [] }>();

const store = useEmberlingsStore();
const picked = ref<string | null>(null);
const starters = computed(() => (store.catalog?.sparks ?? []).filter((s) => s.starter));
const pickedName = computed(() => starters.value.find((s) => s.id === picked.value)?.name ?? "");

async function start(): Promise<void> {
  if (picked.value === null) return;
  if ((await store.createProfile(picked.value)) !== null) emit("started");
}
</script>

<template>
  <section class="starters">
    <button type="button" class="back" @click="emit('back')">Back to menu</button>
    <h3>Choose your first Spark</h3>
    <p class="muted">It stays yours. Other Sparks can be caught in battle or bought in the shop later.</p>
    <div class="starter-grid">
      <button
        v-for="s in starters"
        :key="s.id"
        type="button"
        class="starter"
        :class="{ picked: picked === s.id }"
        :aria-pressed="picked === s.id"
        :disabled="store.busy"
        @click="picked = s.id"
      >
        <span class="starter-name">{{ s.name }}</span>
        <span class="muted">{{ s.abilities.length }} abilities · passive: {{ titleCase(s.passive.kind) }}</span>
      </button>
    </div>
    <button type="button" class="primary start" :disabled="picked === null || store.busy" @click="start">
      {{ picked === null ? "Pick a Spark" : `Start with ${pickedName}` }}
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
.starter:hover:not(:disabled),
.starter.picked {
  border-color: var(--accent);
}
.starter:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.starter-name {
  font-weight: 600;
}
.start {
  margin-top: 16px;
}
@media (prefers-reduced-motion: reduce) {
  .starter {
    transition: none;
  }
}
</style>
