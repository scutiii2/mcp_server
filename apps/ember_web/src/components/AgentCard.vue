<script setup lang="ts">
import type { AgentListing, AgentStatus } from "../api/AgentsClient";

/** One agent on the Agents page: name, id, role badges, what it is for, and
 * whether it is running. The status is an icon and a word, never colour alone. */
defineProps<{ agent: AgentListing }>();

const STATUS_TEXT: Record<AgentStatus, string> = { running: "Running", offline: "Offline", disabled: "Disabled" };
const STATUS_ICON: Record<AgentStatus, string> = { running: "●", offline: "○", disabled: "–" };
</script>

<template>
  <article :class="['agent-card', agent.status, { entry: agent.entry }]">
    <div class="head">
      <h3>{{ agent.label }}</h3>
      <span class="status"><span aria-hidden="true">{{ STATUS_ICON[agent.status] }}</span> {{ STATUS_TEXT[agent.status] }}</span>
    </div>
    <code class="agent-id">{{ agent.id }}</code>
    <div v-if="agent.entry || agent.orchestrator" class="tags">
      <span v-if="agent.entry" class="tag entry-tag">Entry</span>
      <span v-if="agent.orchestrator" class="tag">Orchestrator</span>
    </div>
    <p class="focus">{{ agent.focus || "No description." }}</p>
  </article>
</template>

<style scoped>
.agent-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.agent-card.entry {
  border-color: var(--accent);
}
.agent-card.offline,
.agent-card.disabled {
  color: var(--muted);
}
.head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
h3 {
  margin: 0;
  font-size: 1em;
  font-weight: 600;
  color: var(--text);
}
.status {
  flex-shrink: 0;
  font-size: 0.8em;
  color: var(--muted);
}
.running .status {
  color: var(--success);
}
.agent-id {
  font-family: var(--mono);
  font-size: 0.8em;
  color: var(--muted);
  overflow-wrap: anywhere;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.tag {
  padding: 1px 8px;
  border-radius: var(--radius-sm);
  font-size: 0.75em;
  color: var(--muted);
  background: var(--code-bg);
}
.tag.entry-tag {
  color: var(--accent-contrast);
  background: var(--accent);
}
.focus {
  margin: 0;
  font-size: 0.9em;
}
</style>
