<script setup lang="ts">
import { storeToRefs } from "pinia";
import { onMounted } from "vue";
import { useEntryAgentStore } from "../stores/entryAgent";

const store = useEntryAgentStore();
const { entry, available, loading, loadError } = storeToRefs(store);

onMounted(() => void store.refresh());
</script>

<template>
  <div class="agent-tag" :title="loadError">
    <template v-if="entry">
      Talking to <strong>{{ entry.label }}</strong
      ><span v-if="available === false" class="down"> (unavailable)</span>
    </template>
    <span v-else-if="loading" class="muted">loading ...</span>
    <span v-else class="down">{{ loadError || "No agent is running" }}</span>
    <button
      type="button"
      class="refresh"
      title="Check the agent again"
      :disabled="loading"
      @click="store.refresh()"
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
.agent-tag {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.85em;
  color: var(--muted);
}
.agent-tag strong {
  color: var(--text);
}
.down {
  color: var(--danger);
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
