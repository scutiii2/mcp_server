<script setup lang="ts">
import { computed } from "vue";
import type { WatcherInfo } from "../../api/WatchersClient";
import {
  STATUS_COLORS,
  STATUS_LABELS,
  axisTicks,
  barSpan,
  durationOf,
  intervalOf,
  overlaps,
  statusOf,
  watcherKey,
  type CapabilityGroup,
  type Interval,
} from "../../utils/watchers";

/** Runs over time, one lane per capability. A lane opens (click its name) into one lane per
 * watcher; its own bars then dim. A running run ends in a dot at "now" and a failed one in a tick,
 * so colour is not the only cue. The list below carries the same data as text. */
const props = defineProps<{
  groups: CapabilityGroup[];
  /** Capabilities whose lane is open. */
  expanded: ReadonlySet<string>;
  /** Every lane open, whatever `expanded` says (a focused capability). */
  forceOpen?: boolean;
  window: Interval;
  now: number;
}>();
const emit = defineEmits<{ toggle: [capability: string] }>();

const ticks = computed(() => axisTicks(props.window));
const isOpen = (group: CapabilityGroup) => props.forceOpen || props.expanded.has(group.capability);

interface Bar {
  id: string;
  status: ReturnType<typeof statusOf>;
  left: string;
  width: string;
  title: string;
}

/** The bar for a run, or null when it has no start time or lies outside the window. */
function barOf(w: WatcherInfo): Bar | null {
  const interval = intervalOf(w, props.now);
  if (!interval || !overlaps(w, props.window, props.now)) return null;
  const { from, to } = barSpan(interval, props.window);
  const status = statusOf(w);
  const length = durationOf(w, props.now);
  return {
    id: `${w.capability}/${watcherKey(w)}`,
    status,
    left: `${from * 100}%`,
    width: `${(to - from) * 100}%`,
    title: `${watcherKey(w)} · ${STATUS_LABELS[status]}${length ? ` · ${length}` : ""}`,
  };
}

const bars = (list: WatcherInfo[]) => list.map(barOf).filter((b): b is Bar => b !== null);
</script>

<template>
  <div class="timeline" role="group" aria-label="Watcher runs over time, one lane per capability. The list below has the same details.">
    <div class="row axis" aria-hidden="true">
      <span />
      <div class="ticks">
        <span v-for="t in ticks" :key="t.at" :class="['tick', { first: t.at === 0, last: t.at === 1 }]" :style="{ left: `${t.at * 100}%` }">{{ t.label }}</span>
      </div>
    </div>

    <template v-for="group in groups" :key="group.capability">
      <div class="row">
        <button type="button" class="name cap" :aria-expanded="isOpen(group)" :disabled="forceOpen" @click="emit('toggle', group.capability)">
          <span class="chevron" aria-hidden="true">{{ isOpen(group) ? "▾" : "▸" }}</span>
          <span class="label">{{ group.capability }}</span>
          <span v-if="group.counts.failed" class="alert" :title="`${group.counts.failed} failed`" role="img" :aria-label="`${group.counts.failed} failed`" />
        </button>
        <div :class="['track', { dim: isOpen(group) }]">
          <span v-for="bar in bars(group.watchers)" :key="bar.id" :class="['bar', bar.status]" :style="{ left: bar.left, width: bar.width, '--c': STATUS_COLORS[bar.status] }" :title="bar.title" />
        </div>
      </div>
      <template v-if="isOpen(group)">
        <div v-for="w in group.watchers" :key="`${w.capability}/${watcherKey(w)}`" class="row child">
          <span class="name" :title="watcherKey(w)"><span class="label">{{ watcherKey(w) }}</span></span>
          <div class="track">
            <span
              v-for="bar in bars([w])"
              :key="bar.id"
              :class="['bar', bar.status]"
              :style="{ left: bar.left, width: bar.width, '--c': STATUS_COLORS[bar.status] }"
              :title="bar.title"
            />
          </div>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.timeline {
  --label-w: 150px;
  --gutter: 14px; /* room for the first and last axis label to stick out */
  padding: 0 var(--gutter);
}
.row {
  display: grid;
  grid-template-columns: var(--label-w) minmax(0, 1fr);
  align-items: center;
  height: 26px;
}
.row.child {
  height: 22px;
}
.name {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  padding: 0;
  border: 0;
  background: none;
  color: var(--text);
  font: inherit;
  font-family: var(--mono);
  font-size: 0.75em;
  text-align: left;
}
.name.cap {
  cursor: pointer;
}
.name.cap:disabled {
  cursor: default;
}
.name.cap:hover:not(:disabled) .label {
  text-decoration: underline;
}
.row.child .name {
  padding-left: 14px;
  color: var(--muted);
}
.label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chevron {
  flex: none;
  width: 10px;
  color: var(--muted);
}
.alert {
  flex: none;
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  background: var(--status-failed);
}
.track {
  position: relative;
  height: 100%;
  /* quarter-way hairlines, solid and recessive, with the right edge as the last */
  background: linear-gradient(to right, var(--border) 1px, transparent 1px) 0 0 / 25% 100%;
  border-right: 1px solid var(--border);
}
.track.dim .bar {
  opacity: 0.35;
}
.bar {
  position: absolute;
  top: 50%;
  min-width: 6px;
  height: 14px;
  transform: translateY(-50%);
  border-radius: var(--radius-sm);
  background: var(--c);
}
.row.child .bar {
  height: 12px;
}
/* A running run ends in a dot, a failed one in a tick: shape as well as colour. */
.bar.running::after {
  content: "";
  position: absolute;
  right: -3px;
  top: 50%;
  width: 8px;
  height: 8px;
  transform: translateY(-50%);
  border: 2px solid var(--surface);
  border-radius: var(--radius-full);
  background: var(--c);
  box-sizing: content-box;
}
.bar.failed::after {
  content: "";
  position: absolute;
  right: -1px;
  top: -4px;
  bottom: -4px;
  width: 2px;
  background: var(--c);
}
.axis {
  height: 18px;
  margin-bottom: 2px;
}
.ticks {
  position: relative;
  height: 100%;
}
.tick {
  position: absolute;
  top: 0;
  transform: translateX(-50%);
  font-size: 0.7em;
  color: var(--muted);
  white-space: nowrap;
}
.tick.first {
  transform: none;
}
.tick.last {
  transform: translateX(-100%);
}
@media (max-width: 560px) {
  .timeline {
    --label-w: 104px;
  }
}
</style>
