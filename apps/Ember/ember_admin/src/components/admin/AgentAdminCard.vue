<script setup lang="ts">
import { computed } from "vue";
import type { AgentFile, AgentStatus, AgentTier } from "../../api/AgentsAdminClient";

/** One agent on the admin Agents page, drawn like ember_web's agent card
 * (name, id, role badges, what it is for, provider / gateway / model, status)
 * plus its port and URL and the Edit and Remove buttons. `status` is the live
 * state when known; without it an agent switched off in its file reads
 * Disabled and the others show no state. The status is an icon and a word,
 * never colour alone. */
const props = defineProps<{ agent: AgentFile; status?: AgentStatus; tiers?: AgentTier[] }>();
defineEmits<{ edit: []; remove: [] }>();

const STATUS_TEXT: Record<AgentStatus, string> = { running: "Running", offline: "Offline", disabled: "Disabled" };
const STATUS_ICON: Record<AgentStatus, string> = { running: "●", offline: "○", disabled: "–" };

const shownStatus = computed<AgentStatus | undefined>(() => props.status ?? (props.agent.enabled === false ? "disabled" : undefined));
const rows = computed(() =>
  [
    { label: "Provider", value: props.agent.llm?.provider },
    { label: "Gateway", value: props.agent.llm?.gateway },
    { label: "Model", value: props.agent.llm?.model },
    { label: "Port", value: props.agent.port === undefined ? "" : String(props.agent.port) },
    { label: "URL", value: props.agent.url },
  ].filter((row): row is { label: string; value: string } => !!row.value),
);
</script>

<template>
  <article :class="['agent-card', shownStatus, { entry: agent.entry }]" data-test="agent" :data-id="agent.id">
    <div class="head">
      <button type="button" class="open-card" :aria-label="`Edit ${agent.label || agent.id}`" :disabled="Boolean(agent.error)" @click="$emit('edit')"><h3>{{ agent.label || agent.id }}</h3></button>
      <span v-if="shownStatus" class="status" data-test="status"><span aria-hidden="true">{{ STATUS_ICON[shownStatus] }}</span> {{ STATUS_TEXT[shownStatus] }}</span>
    </div>
    <code class="agent-id">{{ agent.id }}</code>
    <div v-if="agent.entry || agent.orchestrator" class="tags">
      <span v-if="agent.entry" class="tag entry-tag">Entry</span>
      <span v-if="agent.orchestrator" class="tag">Orchestrator</span>
    </div>
    <p v-if="agent.error" class="problem" role="alert">{{ agent.error }}</p>
    <template v-else>
      <p class="focus">{{ agent.focus || "No description." }}</p>
      <div v-if="rows.length || tiers?.length" class="llm">
        <dl v-if="rows.length">
          <template v-for="row in rows" :key="row.label">
            <dt>{{ row.label }}</dt>
            <dd>{{ row.value }}</dd>
          </template>
        </dl>
        <ul v-if="tiers?.length" class="tiers" aria-label="Model tiers">
          <li v-for="t in tiers" :key="t.tier">
            <span class="tier" :title="t.use_for">{{ t.tier }}</span>
            <span class="tier-model" :title="t.use_for">{{ t.id }}</span>
          </li>
        </ul>
      </div>
    </template>
    <div class="buttons">
      <button type="button" class="chip" data-test="edit" :disabled="Boolean(agent.error)" @click="$emit('edit')">Edit</button>
      <button
        type="button"
        class="remove"
        data-test="remove"
        :disabled="agent.entry === true"
        :title="agent.entry ? 'The entry agent cannot be removed. Make another agent the entry first.' : undefined"
        @click="$emit('remove')"
      >Remove</button>
    </div>
  </article>
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
.agent-card.entry { border-color: var(--accent); }
.agent-card.offline, .agent-card.disabled { color: var(--muted); }
.agent-card:hover { border-color: var(--accent); }
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
.open-card:disabled { cursor: default; }
.open-card::after { content: ""; position: absolute; inset: 0; border-radius: var(--radius-lg); }
.open-card:focus-visible { outline: none; }
.open-card:focus-visible::after { box-shadow: inset 0 0 0 2px var(--accent); }
.head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
h3 { margin: 0; font-size: 1em; font-weight: 600; color: var(--text); }
.status { flex-shrink: 0; font-size: 0.8em; color: var(--muted); }
.running .status { color: var(--success); }
.agent-id { font-family: var(--mono); font-size: 0.8em; color: var(--muted); overflow-wrap: anywhere; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; }
.tag { padding: 1px 8px; border-radius: var(--radius-sm); font-size: 0.75em; color: var(--muted); background: var(--code-bg); }
.tag.entry-tag { color: var(--accent-contrast); background: var(--accent); }
.focus {
  margin: 0;
  font-size: 0.9em;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
}
.problem { margin: 0; color: var(--danger); font-size: 0.9em; overflow-wrap: anywhere; }
.llm {
  margin: 4px 0 0;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  font-size: 0.8em;
}
.llm { display: flex; flex-direction: column; gap: 6px; }
dl, .tiers { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 3px 10px; margin: 0; }
.tiers { padding: 0; list-style: none; }
.tiers li { display: contents; }
dt, .tier { color: var(--muted); }
dd, .tier-model { margin: 0; font-family: var(--mono); overflow-wrap: anywhere; }
/* Above the card-wide open button, so the buttons stay clickable. */
.buttons { position: relative; z-index: 1; display: flex; gap: 6px; margin-top: auto; padding-top: 8px; }
.chip { padding: 4px 12px; border: 1px solid var(--border); border-radius: var(--radius-full); background: transparent; color: var(--text); font: inherit; cursor: pointer; }
.remove { padding: 4px 12px; border: 1px solid var(--danger); border-radius: var(--radius-full); background: transparent; color: var(--danger); font: inherit; cursor: pointer; }
.remove:disabled, .chip:disabled { opacity: 0.5; cursor: default; }
:is(button):focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
</style>
