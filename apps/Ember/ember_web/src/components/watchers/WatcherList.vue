<script setup lang="ts">
import {
  STATUS_COLORS,
  STATUS_ICONS,
  STATUS_LABELS,
  durationOf,
  intervalOf,
  statusOf,
  timeAgo,
  watcherKey,
  type CapabilityGroup,
} from "../../utils/watchers";

/** The runs as text, by capability: the timeline's twin. Each capability folds open and shut with
 * the same state as its timeline lane. Failed runs are washed red and listed first. */
const props = defineProps<{ groups: CapabilityGroup[]; expanded: ReadonlySet<string>; forceOpen?: boolean; now: number }>();
const emit = defineEmits<{ toggle: [capability: string] }>();

const isOpen = (capability: string) => props.forceOpen || props.expanded.has(capability);

function when(iso: string | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "";
}

/** "5m ago" for the last thing that happened to the run: its end, or its start while it runs. */
function ago(w: Parameters<typeof intervalOf>[0]): string {
  const interval = intervalOf(w, props.now);
  if (!interval) return "";
  return timeAgo(statusOf(w) === "running" ? interval.start : interval.end, props.now);
}
</script>

<template>
  <div class="list">
    <section v-for="group in groups" :key="group.capability">
      <button type="button" class="head" :aria-expanded="isOpen(group.capability)" :disabled="forceOpen" @click="emit('toggle', group.capability)">
        <span class="chevron" aria-hidden="true">{{ isOpen(group.capability) ? "▾" : "▸" }}</span>
        <span class="cap">{{ group.capability }}</span>{{ " " }}
        <span v-if="group.counts.failed" class="count failed">{{ group.counts.failed }} failed</span>{{ " " }}
        <span v-if="group.counts.running" class="count running">{{ group.counts.running }} running</span>{{ " " }}
        <span class="count">{{ group.watchers.length }} {{ group.watchers.length === 1 ? "watcher" : "watchers" }}</span>
      </button>
      <ul v-if="isOpen(group.capability)" class="rows">
        <li v-for="w in group.watchers" :key="`${w.capability}/${watcherKey(w)}`" :class="['row', statusOf(w)]">
          <div class="line">
            <span class="key">{{ watcherKey(w) }}</span>
            <span class="status" :style="{ color: STATUS_COLORS[statusOf(w)] }">
              <span aria-hidden="true">{{ STATUS_ICONS[statusOf(w)] }}</span>
              {{ STATUS_LABELS[statusOf(w)] }}
            </span>
            <span class="duration">{{ durationOf(w, now) }}</span>
            <span class="ago">{{ ago(w) }}</span>
          </div>
          <div v-if="w.started_at" class="sub">
            Started {{ when(w.started_at) }}
            <template v-if="statusOf(w) !== 'running' && w.last_polled_at"> · Finished {{ when(w.last_polled_at) }}</template>
          </div>
          <div v-if="w.recipients?.length" class="sub">Recipients: {{ w.recipients.join(", ") }}</div>
          <details v-if="w.detail && Object.keys(w.detail).length">
            <summary>Detail</summary>
            <pre>{{ JSON.stringify(w.detail, null, 2) }}</pre>
          </details>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 14px;
  border: 0;
  border-bottom: 1px solid var(--border);
  background: var(--code-bg);
  color: var(--text);
  font: inherit;
  font-size: 0.85em;
  text-align: left;
  cursor: pointer;
}
.head:disabled {
  cursor: default;
}
.chevron {
  width: 10px;
  color: var(--muted);
}
.cap {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  font-family: var(--mono);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.count {
  font-size: 0.9em;
  color: var(--muted);
}
.count.failed {
  color: var(--status-failed);
}
.count.running {
  color: var(--status-running);
}
.rows {
  margin: 0;
  padding: 0;
  list-style: none;
}
.row {
  padding: 8px 14px 8px 32px;
  border-bottom: 1px solid var(--border);
  font-size: 0.85em;
}
.row.failed {
  background: color-mix(in srgb, var(--status-failed) 9%, transparent);
}
.line {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 14px;
}
.key {
  flex: 1 1 180px;
  min-width: 0;
  overflow-wrap: anywhere;
  font-family: var(--mono);
}
.status {
  white-space: nowrap;
}
.duration {
  min-width: 72px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.ago {
  min-width: 64px;
  text-align: right;
  color: var(--muted);
}
.sub {
  margin-top: 2px;
  font-size: 0.9em;
  color: var(--muted);
  overflow-wrap: anywhere;
}
details {
  margin-top: 4px;
}
details summary {
  cursor: pointer;
  font-size: 0.9em;
  color: var(--muted);
}
</style>
