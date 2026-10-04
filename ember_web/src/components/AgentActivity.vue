<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed } from "vue";
import { useChatStore } from "../stores/chat";
import { useEntryAgentStore } from "../stores/entryAgent";
import ElapsedTime from "./ElapsedTime.vue";

/** While an answer is written: which agent is working ("Ember → Calculator")
 * and for how long the innermost one has. Hidden when only the main agent works. */
const { activeAgents } = storeToRefs(useChatStore());
const { entry } = storeToRefs(useEntryAgentStore());

const chain = computed(() =>
  [entry.value?.label ?? "Agent", ...activeAgents.value.map((a) => a.label || a.agent_id)].join(" → "),
);
const since = computed(() => {
  const innermost = activeAgents.value[activeAgents.value.length - 1];
  const parsed = innermost ? Date.parse(innermost.since) : NaN;
  return Number.isNaN(parsed) ? null : parsed;
});
</script>

<template>
  <div v-if="activeAgents.length" class="agent-activity" role="status">
    <span class="dot" />{{ chain }}<template v-if="since !== null"> · <ElapsedTime :since="since" /></template>
  </div>
</template>

<style scoped>
.agent-activity {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  font-size: 0.85em;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
  50% {
    opacity: 0.3;
  }
}
</style>
