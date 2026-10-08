<script setup lang="ts">
import type { TurnNotice } from "../api/types";

defineProps<{ notices: TurnNotice[] }>();
defineEmits<{ dismiss: [] }>();
</script>

<template>
  <div v-if="notices.length" class="notices" role="status">
    <ul>
      <li v-for="n in notices" :key="n.id">
        <strong>{{ n.label }}</strong> wasn't used in this answer: {{ n.error }}
      </li>
    </ul>
    <button type="button" @click="$emit('dismiss')">Dismiss</button>
  </div>
</template>

<style scoped>
.notices {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 16px;
  font-size: 0.9em;
  color: var(--muted);
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
ul {
  margin: 0;
  padding: 0;
  list-style: none;
}
button {
  padding: 2px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  cursor: pointer;
  color: inherit;
  background: transparent;
}
button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>
