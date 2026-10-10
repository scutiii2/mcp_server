<script setup lang="ts">
import { computed, ref } from "vue";
import { useEmberlingsStore } from "../../stores/emberlings";
import SparkTemplateCard from "./SparkTemplateCard.vue";

/** New game: pick the first Spark, then start. Back returns to the menu. */
const emit = defineEmits<{ back: []; started: [] }>();

const store = useEmberlingsStore();
const picked = ref<string | null>(null);
const starters = computed(() => (store.catalog?.sparks ?? []).filter((s) => s.starter));
const pickedName = computed(() => starters.value.find((s) => s.id === picked.value)?.name ?? "");

function pick(id: string): void {
  if (!store.busy) picked.value = id;
}

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
      <div v-for="s in starters" :key="s.id" class="starter" :class="{ picked: picked === s.id }">
        <div class="starter-card" @click="pick(s.id)">
          <SparkTemplateCard :spark="s" />
        </div>
        <button
          type="button"
          class="starter-pick"
          :aria-pressed="picked === s.id"
          :disabled="store.busy"
          @click="pick(s.id)"
        >
          {{ picked === s.id ? "Picked" : `Pick ${s.name}` }}
        </button>
      </div>
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
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 12px;
}
.starter {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 300px;
}
.starter-card {
  border-radius: var(--radius-md);
  cursor: pointer;
}
.starter.picked .starter-card {
  outline: 3px solid var(--accent);
  outline-offset: 2px;
}
.starter-pick {
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--surface);
  font: inherit;
  cursor: pointer;
}
.starter-pick:hover:not(:disabled),
.starter-pick:focus-visible {
  border-color: var(--accent);
}
.starter.picked .starter-pick {
  border-color: var(--accent);
  color: var(--accent-contrast);
  background: var(--accent);
  font-weight: 600;
}
.start {
  margin-top: 16px;
}
</style>
