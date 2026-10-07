<script setup lang="ts">
import { computed, ref } from "vue";
import type { AgentListing, AgentStatus } from "../api/AgentsClient";
import AgentLlm from "./AgentLlm.vue";

/** Agents as a left-to-right node map. Edges are inferred from the
 * entry / orchestrator flags, not real delegation data: entry agents feed the
 * orchestrators, and orchestrators feed the rest (entry feeds the rest when
 * there is no orchestrator). */
const props = defineProps<{ agents: AgentListing[] }>();

const NODE_W = 170;
const NODE_H = 64;
const GAP_X = 64; // between columns (room for the edges)
const GAP_Y = 16; // between nodes in a column
const PAD = 16;

const STATUS_ICON: Record<AgentStatus, string> = { running: "●", offline: "○", disabled: "–" };
const STATUS_TEXT: Record<AgentStatus, string> = { running: "Running", offline: "Offline", disabled: "Disabled" };

/** The clicked agent; falls back to the entry agent (or the first) so the
 * details panel is never empty, and when the chosen agent disappears on refresh. */
const pickedId = ref<string | null>(null);
const selected = computed<AgentListing | null>(
  () =>
    props.agents.find((a) => a.id === pickedId.value) ??
    props.agents.find((a) => a.entry) ??
    props.agents[0] ??
    null,
);

interface Placed {
  agent: AgentListing;
  x: number;
  y: number;
}

const layers = computed<AgentListing[][]>(() => {
  const entry = props.agents.filter((a) => a.entry);
  const orchestrators = props.agents.filter((a) => !a.entry && a.orchestrator);
  const rest = props.agents.filter((a) => !a.entry && !a.orchestrator);
  return [entry, orchestrators, rest].filter((layer) => layer.length > 0);
});

const width = computed(() => PAD * 2 + layers.value.length * NODE_W + (layers.value.length - 1) * GAP_X);
const height = computed(() => {
  const tallest = Math.max(1, ...layers.value.map((l) => l.length));
  return PAD * 2 + tallest * NODE_H + (tallest - 1) * GAP_Y;
});

const placed = computed<Placed[][]>(() =>
  layers.value.map((layer, col) => {
    const colHeight = layer.length * NODE_H + (layer.length - 1) * GAP_Y;
    const top = (height.value - colHeight) / 2;
    return layer.map((agent, row) => ({
      agent,
      x: PAD + col * (NODE_W + GAP_X),
      y: top + row * (NODE_H + GAP_Y),
    }));
  }),
);

const edges = computed(() => {
  const out: { key: string; d: string; live: boolean; from: string; to: string }[] = [];
  for (let row = 0; row < placed.value.length - 1; row++) {
    for (const from of placed.value[row]) {
      for (const to of placed.value[row + 1]) {
        const x1 = from.x + NODE_W;
        const y1 = from.y + NODE_H / 2;
        const x2 = to.x;
        const y2 = to.y + NODE_H / 2;
        const mid = (x1 + x2) / 2;
        out.push({
          key: `${from.agent.id}>${to.agent.id}`,
          d: `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`,
          from: from.agent.id,
          to: to.agent.id,
          live: from.agent.status === "running" && to.agent.status === "running",
        });
      }
    }
  }
  return out;
});

const handsTo = computed(() =>
  edges.value.filter((e) => e.from === selected.value?.id).map((e) => e.to),
);
const handedBy = computed(() =>
  edges.value.filter((e) => e.to === selected.value?.id).map((e) => e.from),
);
const labelOf = (id: string) => props.agents.find((a) => a.id === id)?.label ?? id;
const touches = (e: { from: string; to: string }) => e.from === selected.value?.id || e.to === selected.value?.id;
</script>

<template>
  <div class="host">
  <div class="layout">
  <div class="map-scroll">
    <div class="map" :style="{ width: `${width}px`, height: `${height}px` }">
      <svg class="edges" :width="width" :height="height" aria-hidden="true">
        <path v-for="e in edges" :key="e.key" :d="e.d" :class="{ live: e.live, picked: touches(e) }" />
      </svg>
      <template v-for="row in placed" :key="row[0].agent.id">
        <button
          v-for="n in row"
          :key="n.agent.id"
          type="button"
          :class="['node', n.agent.status, { entry: n.agent.entry, picked: n.agent.id === selected?.id }]"
          :aria-pressed="n.agent.id === selected?.id"
          @click="pickedId = n.agent.id"
          :style="{ left: `${n.x}px`, top: `${n.y}px`, width: `${NODE_W}px`, height: `${NODE_H}px` }"
          :title="n.agent.focus || n.agent.id"
        >
          <div class="head">
            <h3>{{ n.agent.label }}</h3>
            <span class="status" :aria-label="n.agent.status">{{ STATUS_ICON[n.agent.status] }}</span>
          </div>
          <code class="agent-id">{{ n.agent.id }}</code>
          <span v-if="n.agent.entry" class="tag">Entry</span>
          <span v-else-if="n.agent.orchestrator" class="tag">Orchestrator</span>
        </button>
      </template>
    </div>
  </div>

  <section v-if="selected" class="details" aria-live="polite">
    <div class="d-head">
      <h3>{{ selected.label }}</h3>
      <span :class="['d-status', selected.status]">{{ STATUS_ICON[selected.status] }} {{ STATUS_TEXT[selected.status] }}</span>
    </div>
    <code class="agent-id">{{ selected.id }}</code>
    <div v-if="selected.entry || selected.orchestrator" class="d-tags">
      <span v-if="selected.entry" class="tag entry-tag">Entry</span>
      <span v-if="selected.orchestrator" class="tag">Orchestrator</span>
    </div>
    <p class="d-focus">{{ selected.focus || "No description." }}</p>
    <AgentLlm :agent="selected" />
    <dl class="d-links">
      <div>
        <dt>Receives work from</dt>
        <dd>{{ handedBy.length ? handedBy.map(labelOf).join(", ") : selected.entry ? "New chats" : "–" }}</dd>
      </div>
      <div>
        <dt>Hands work to</dt>
        <dd>{{ handsTo.length ? handsTo.map(labelOf).join(", ") : "–" }}</dd>
      </div>
    </dl>
    <p class="d-note">Connections are inferred from the entry and orchestrator roles.</p>
  </section>
  </div>
  </div>
</template>

<style scoped>
.host {
  container-type: inline-size;
}
.layout > .map-scroll {
  overflow: auto;
  padding: 4px 0;
}
/* Wide: details become a side panel beside the map. */
@container (min-width: 900px) {
  .layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 260px;
    gap: 16px;
    align-items: start;
  }
  .details {
    margin-top: 0;
    position: sticky;
    top: 0;
  }
}
.map {
  position: relative;
  margin: 0 auto;
}
.edges {
  position: absolute;
  inset: 0;
}
.edges path {
  fill: none;
  stroke: var(--border);
  stroke-width: 1.5;
  stroke-dasharray: 4 4;
}
.edges path.picked {
  stroke-width: 2.5;
}
.edges path.live {
  stroke: var(--accent);
  stroke-dasharray: none;
  opacity: 0.6;
}
.node {
  position: absolute;
  font: inherit;
  text-align: left;
  color: inherit;
  cursor: pointer;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
  overflow: hidden;
}
.node.entry {
  border-color: var(--accent);
}
.node.picked {
  box-shadow: 0 0 0 2px var(--accent);
}
.node:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.node.offline,
.node.disabled {
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
  font-size: 0.95em;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.status {
  color: var(--muted);
}
.running .status {
  color: var(--success);
}
.agent-id {
  font-family: var(--mono);
  font-size: 0.75em;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tag {
  align-self: flex-start;
  padding: 0 6px;
  border-radius: var(--radius-sm);
  font-size: 0.7em;
  color: var(--muted);
  background: var(--code-bg);
}
.node.entry .tag {
  color: var(--accent-contrast);
  background: var(--accent);
}
.details {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 12px;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.d-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.d-head h3 {
  font-size: 1.05em;
  white-space: normal;
}
.d-status {
  font-size: 0.85em;
  color: var(--muted);
}
.d-status.running {
  color: var(--success);
}
.d-tags {
  display: flex;
  gap: 6px;
}
.d-tags .tag {
  font-size: 0.75em;
}
.tag.entry-tag {
  color: var(--accent-contrast);
  background: var(--accent);
}
.d-focus {
  margin: 0;
}
.d-links {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 32px;
  margin: 4px 0 0;
}
.d-links dt {
  font-size: 0.75em;
  color: var(--muted);
}
.d-links dd {
  margin: 0;
}
.d-note {
  margin: 4px 0 0;
  font-size: 0.75em;
  color: var(--muted);
}
</style>
