<script setup lang="ts">
import { storeToRefs } from "pinia";
import { onMounted } from "vue";
import { useAgentsStore } from "../stores/agents";

// locked: a turn is running - its agent can't change mid-answer.
defineProps<{ locked: boolean }>();

const agentsStore = useAgentsStore();
const { agents, available, selected, loading, loadError } = storeToRefs(agentsStore);

onMounted(() => void agentsStore.refresh());

function onChange(event: Event): void {
  agentsStore.select((event.target as HTMLSelectElement).value);
}
</script>

<template>
  <div class="agent-picker">
    <label for="agent-select">Agent</label>
    <select
      id="agent-select"
      :value="selected?.id ?? ''"
      :disabled="locked || agents.length === 0"
      :title="loadError"
      @change="onChange"
    >
      <option v-if="agents.length === 0" value="">{{ loading ? "loading ..." : "no agents available" }}</option>
      <option v-for="a in agents" :key="a.id" :value="a.id">
        {{ a.label }}{{ available[a.id] === false ? " (unavailable)" : "" }}
      </option>
    </select>
    <button
      type="button"
      class="refresh"
      title="Reload agent list"
      :disabled="loading"
      @click="agentsStore.refresh()"
    >
      <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true" :class="{ spin: loading }">
        <path
          d="M20 12a8 8 0 1 1-2.34-5.66M20 4v5h-5"
          fill="none"
          stroke="currentColor"
          stroke-width="2.2"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </button>
  </div>
</template>

<style scoped>
.agent-picker {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.85em;
  color: var(--muted);
}
select {
  max-width: 240px;
  padding: 3px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
}
select:focus {
  outline: none;
  border-color: var(--accent);
}
.refresh {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: none;
  border-radius: 50%;
  cursor: pointer;
  color: var(--muted);
  background: transparent;
}
.refresh:hover:not(:disabled) {
  color: var(--text);
}
.spin {
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
