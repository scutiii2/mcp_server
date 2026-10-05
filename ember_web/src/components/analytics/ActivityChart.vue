<script setup lang="ts">
import { computed, ref } from "vue";
import type { AnalyticsReport, LogKind } from "../../api/LogsClient";
import {
  KIND_COLORS,
  KIND_LABELS,
  axisLabel,
  bucketTitle,
  formatCount,
  niceCeil,
} from "../../utils/logAnalytics";

/** Entries over time: one stacked column per bucket, a segment per log kind
 * (bottom to top in `kinds` order). Hover, or the arrow keys once it has focus,
 * reads a bucket in one tooltip for every kind; the table twin shows the same
 * numbers without either. Buckets are UTC. */
const props = defineProps<{
  series: AnalyticsReport["series"];
  kinds: LogKind[];
  bucket: AnalyticsReport["bucket"];
  /** Refetching: keep the last render, dimmed. */
  loading?: boolean;
}>();

const MAX_TICKS = 6;

const plot = ref<HTMLElement | null>(null);
const active = ref<number | null>(null);
const asTable = ref(false);

const countOf = (index: number, kind: LogKind) => props.series[index]?.counts[kind] ?? 0;
const totalOf = (index: number) => props.kinds.reduce((sum, kind) => sum + countOf(index, kind), 0);

const top = computed(() => niceCeil(Math.max(0, ...props.series.map((_, i) => totalOf(i)))));
const empty = computed(() => props.series.every((_, i) => totalOf(i) === 0));
const columns = computed(() =>
  props.series.map((_, i) => {
    const segments = props.kinds.filter((kind) => countOf(i, kind) > 0).map((kind) => ({ kind, count: countOf(i, kind) }));
    return { height: (totalOf(i) / top.value) * 100, segments };
  }),
);
const ticks = computed(() => [top.value, top.value / 2, 0]);
const labelEvery = computed(() => Math.ceil(props.series.length / MAX_TICKS));

const tooltipStyle = computed(() => {
  if (active.value === null) return {};
  const share = (active.value + 0.5) / props.series.length;
  const anchor = share < 0.2 ? "0" : share > 0.8 ? "-100%" : "-50%";
  // The plot is the area minus its side padding (see .area).
  return { left: `calc(18px + (100% - 36px) * ${share})`, transform: `translateX(${anchor})` };
});

function select(event: PointerEvent): void {
  const box = plot.value?.getBoundingClientRect();
  if (!box || box.width === 0) return;
  const share = (event.clientX - box.left) / box.width;
  active.value = Math.min(props.series.length - 1, Math.max(0, Math.floor(share * props.series.length)));
}

function onKey(event: KeyboardEvent): void {
  const last = props.series.length - 1;
  const move: Record<string, number | null> = {
    ArrowLeft: Math.max(0, (active.value ?? last + 1) - 1),
    ArrowRight: Math.min(last, (active.value ?? -1) + 1),
    Home: 0,
    End: last,
    Escape: null,
  };
  if (!(event.key in move)) return;
  event.preventDefault();
  active.value = move[event.key] ?? null;
}
</script>

<template>
  <figure :class="['chart', { dim: loading }]">
    <div class="head">
      <ul class="legend">
        <li v-for="kind in kinds" :key="kind"><span class="swatch" :style="{ background: KIND_COLORS[kind] }" />{{ KIND_LABELS[kind] }}</li>
      </ul>
      <button type="button" class="chip" :aria-pressed="asTable" @click="asTable = !asTable">
        {{ asTable ? "Show chart" : "Show table" }}
      </button>
    </div>

    <div v-if="!asTable" class="frame">
      <div class="yaxis" aria-hidden="true">
        <span v-for="t in ticks" :key="t" class="ytick" :style="{ bottom: `${(t / top) * 100}%` }">{{ formatCount(t) }}</span>
      </div>
      <div class="area">
        <div class="gridlines" aria-hidden="true">
          <span v-for="t in ticks" :key="t" class="gridline" :style="{ bottom: `${(t / top) * 100}%` }" />
        </div>
        <div
          ref="plot"
          class="plot"
          role="group"
          tabindex="0"
          aria-label="Entries over time. Use the left and right arrow keys to read each period."
          @pointermove="select"
          @pointerleave="active = null"
          @blur="active = null"
          @keydown="onKey"
        >
          <div v-for="(column, i) in columns" :key="series[i]!.bucket" :class="['col', { active: active === i }]">
            <div class="stack" :style="{ height: `${column.height}%` }">
              <span
                v-for="(segment, s) in column.segments"
                :key="segment.kind"
                :class="['seg', { cap: s === column.segments.length - 1 }]"
                :style="{ flexGrow: segment.count, background: KIND_COLORS[segment.kind] }"
              />
            </div>
          </div>
        </div>
        <p v-if="empty" class="none">No entries in this range.</p>
        <div v-if="active !== null" class="tooltip" role="status" :style="tooltipStyle">
          <strong class="when">{{ bucketTitle(series[active]!.bucket, bucket) }}</strong>
          <span v-for="kind in kinds" :key="kind" class="line">
            <span class="key" :style="{ background: KIND_COLORS[kind] }" />
            <strong>{{ countOf(active, kind).toLocaleString() }}</strong>{{ " " }}<span class="name">{{ KIND_LABELS[kind] }}</span>
          </span>
        </div>
        <div class="xaxis" aria-hidden="true">
          <span v-for="(point, i) in series" :key="point.bucket" class="xcell">
            <span v-if="i % labelEvery === 0" class="xtick">{{ axisLabel(point.bucket, bucket) }}</span>
          </span>
        </div>
      </div>
    </div>

    <div v-else class="table-wrap">
      <table>
        <caption class="sr-only">
          Entries per {{ bucket }}, UTC
        </caption>
        <thead>
          <tr>
            <th scope="col">{{ bucket === "hour" ? "Hour" : "Day" }} (UTC)</th>
            <th v-for="kind in kinds" :key="kind" scope="col">{{ KIND_LABELS[kind] }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(point, i) in series" :key="point.bucket">
            <th scope="row">{{ bucketTitle(point.bucket, bucket) }}</th>
            <td v-for="kind in kinds" :key="kind">{{ countOf(i, kind).toLocaleString() }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </figure>
</template>

<style scoped>
.chart {
  margin: 0;
  transition: opacity 0.15s;
}
.chart.dim {
  opacity: 0.5;
}
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: 0.8em;
  color: var(--muted);
}
.legend li {
  display: flex;
  align-items: center;
  gap: 6px;
}
.swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}

.frame {
  display: grid;
  grid-template-columns: 2.6em minmax(0, 1fr);
  gap: 6px;
}
/* Only the plot has a fixed height; the axis rows below it add their own. */
.yaxis {
  position: relative;
  height: 160px;
}
.ytick {
  position: absolute;
  right: 0;
  transform: translateY(50%);
  font-size: 0.72em;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.area {
  position: relative;
  padding: 0 18px; /* room for the first and last x label to stick out */
  margin: 0 -18px;
}
.gridlines {
  position: absolute;
  inset: 0 18px auto;
  height: 160px;
}
.gridline {
  position: absolute;
  left: 0;
  right: 0;
  height: 1px;
  background: var(--border);
}
.gridline:last-child {
  background: color-mix(in srgb, var(--muted) 45%, var(--border));
}
.plot {
  position: relative;
  display: flex;
  align-items: flex-end;
  height: 160px;
  border-radius: 4px;
}
.plot:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.col {
  display: flex;
  flex: 1 1 0;
  align-items: flex-end;
  justify-content: center;
  min-width: 0;
  height: 100%;
}
.col.active {
  background: color-mix(in srgb, var(--text) 6%, transparent);
}
.stack {
  display: flex;
  flex-direction: column-reverse;
  gap: 2px; /* the surface gap between segments */
  width: calc(100% - 2px); /* and between neighbouring columns */
  max-width: 24px;
}
.seg {
  flex-basis: 0;
  flex-shrink: 1;
  min-height: 2px;
}
.seg.cap {
  border-radius: 4px 4px 0 0;
}
.col.active .seg {
  filter: brightness(1.12);
}
.none {
  position: absolute;
  top: 0;
  left: 18px;
  right: 18px;
  height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  color: var(--muted);
  font-size: 0.85em;
  pointer-events: none;
}
.tooltip {
  position: absolute;
  top: 4px;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  box-shadow: 0 4px 14px rgb(0 0 0 / 0.12);
  font-size: 0.8em;
  white-space: nowrap;
  pointer-events: none;
}
.when {
  margin-bottom: 2px;
  color: var(--muted);
  font-weight: 500;
}
.line {
  display: block; /* inline children keep real spaces between value and name */
}
.key {
  display: inline-block;
  width: 10px;
  height: 2px;
  margin-right: 6px;
  vertical-align: middle;
}
.name {
  color: var(--muted);
}
.xaxis {
  display: flex;
  margin-top: 6px;
  padding: 0 18px;
}
.xcell {
  position: relative;
  flex: 1 1 0;
  min-width: 0;
  height: 1.2em;
}
.xtick {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  font-size: 0.72em;
  color: var(--muted);
  white-space: nowrap;
}

.table-wrap {
  max-height: 260px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8em;
}
th,
td {
  padding: 5px 10px;
  text-align: right;
  border-bottom: 1px solid var(--border);
}
th[scope="row"],
thead th:first-child {
  text-align: left;
}
thead th {
  position: sticky;
  top: 0;
  background: var(--surface);
  color: var(--muted);
  font-weight: 500;
}
tbody th {
  font-weight: 400;
}
td {
  font-variant-numeric: tabular-nums;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
</style>
