<script setup lang="ts">
import { ref } from "vue";
import type { AgentListing, AgentStatus } from "../api/AgentsClient";
import AgentLlm from "./AgentLlm.vue";
import BaseModal from "./BaseModal.vue";

/** One agent on the Agents page: name, id, role badges, what it is for, its
 * provider / gateway / model, and whether it is running. The card opens a dialog with the full description. The status is an icon and a word, never colour alone. */
defineProps<{ agent: AgentListing }>();
const opened = ref(false);

const STATUS_TEXT: Record<AgentStatus, string> = { running: "Running", offline: "Offline", disabled: "Disabled" };
const STATUS_ICON: Record<AgentStatus, string> = { running: "●", offline: "○", disabled: "–" };
</script>

<template>
  <article :class="['agent-card', agent.status, { entry: agent.entry }]">
    <div class="head">
      <button type="button" class="open-card" aria-haspopup="dialog" :aria-label="`Open ${agent.label}`" @click="opened = true"><h3>{{ agent.label }}</h3></button>
      <span class="status"><span aria-hidden="true">{{ STATUS_ICON[agent.status] }}</span> {{ STATUS_TEXT[agent.status] }}</span>
    </div>
    <code class="agent-id">{{ agent.id }}</code>
    <div v-if="agent.entry || agent.orchestrator" class="tags">
      <span v-if="agent.entry" class="tag entry-tag">Entry</span>
      <span v-if="agent.orchestrator" class="tag">Orchestrator</span>
    </div>
    <p class="focus">{{ agent.focus || "No description." }}</p>
    <AgentLlm :agent="agent" />
  </article>
  <BaseModal :open="opened" :title="agent.label" @close="opened = false">
    <code class="agent-id">{{ agent.id }}</code>
    <p class="full-focus">{{ agent.focus || "No description." }}</p>
    <AgentLlm :agent="agent" />
  </BaseModal>
</template>

<style scoped>
.agent-card {
  position: relative;
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
.open-card {
  min-width: 0;
  padding: 0;
  border: none;
  background: none;
  color: inherit;
  text-align: left;
  cursor: pointer;
  font: inherit;
}
.open-card::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: var(--radius-lg);
}
.open-card:focus-visible {
  outline: none;
}
.open-card:focus-visible::after {
  box-shadow: inset 0 0 0 2px var(--accent);
}
.agent-card:hover {
  border-color: var(--accent);
}
.full-focus {
  margin: 8px 0;
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
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
}
</style>
