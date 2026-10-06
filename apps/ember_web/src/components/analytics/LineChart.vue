<script setup lang="ts">
import { computed, ref, useTemplateRef } from "vue";
import { axisLabel, bucketTitle, formatCount, niceCeil, type BucketSize } from "../../utils/logAnalytics";
import { useBucketCursor, type ChartPart } from "./useBucketCursor";

/** Values over time: one 2px line per part, a point per bucket. A bucket with no
 * value (`null`, e.g. no requests so no latency) leaves a gap rather than a zero;
 * a point with no neighbour is drawn as a dot. Hover, or the arrow keys once it
 * has focus, reads one bucket for every line; the table twin shows the same
 * numbers. Buckets are UTC. Share the frame and reading controls with ActivityChart. */
const props = withDefaults(
  defineProps<{
    series: { bucket: string; values: Partial<Record<string, number | null>> }[];
    lines: ChartPart[];
    bucket: BucketSize;
    /** What the values are ("Response time"): names the chart for screen readers and the table. */
    label: string;
    /** How a value is written on the axis, in the tooltip and in the table. */
    format?: (value: number) => string;
    emptyText?: string;
    /** Refetching: keep the last render, dimmed. */
    loading?: boolean;
  }>(),
  { format: formatCount, emptyText: "Nothing in this range." },
);

const plot = useTemplateRef<HTMLElement>("plot");
const { active, labelEvery, tooltipStyle, select, onKey } = useBucketCursor(plot, () => props.series.length);
const asTable = ref(false);

const valueOf = (index: number, line: ChartPart): number | null => props.series[index]?.values[line.id] ?? null;

const top = computed(() =>
  niceCeil(Math.max(0, ...props.series.flatMap((_, i) => props.lines.map((line) => valueOf(i, line) ?? 0)))),
);
const empty = computed(() => props.series.every((_, i) => props.lines.every((line) => valueOf(i, line) === null)));
const ticks = computed(() => [top.value, top.value / 2, 0]);

const xShare = (index: number) => ((index + 0.5) / props.series.length) * 100;
const yShare = (value: number) => (value / top.value) * 100;

interface Point {
  x: number;
  value: number;
}
const drawn = computed(() =>
  props.lines.map((line) => {
    // Runs of consecutive buckets that have a value; a null ends a run.
    const runs: Point[][] = [];
    let run: Point[] = [];
    props.series.forEach((_, i) => {
      const value = valueOf(i, line);
      if (value === null) {
        if (run.length) runs.push(run);
        run = [];
      } else run.push({ x: xShare(i), value });
    });
    if (run.length) runs.push(run);
    return {
      line,
      // The SVG is a 0-100 square stretched over the plot; y is flipped (0 is the top).
      paths: runs.filter((r) => r.length > 1).map((r) => r.map((p) => `${p.x.toFixed(2)},${(100 - yShare(p.value)).toFixed(2)}`).join(" ")),
      dots: runs.filter((r) => r.length === 1).map((r) => r[0]!),
    };
  }),
);

const reading = computed(() =>
  active.value === null
    ? []
    : props.lines.flatMap((line) => {
        const value = valueOf(active.value!, line);
        return value === null ? [] : [{ line, x: xShare(active.value!), value }];
      }),
);
const shown = (value: number | null) => (value === null ? "–" : props.format(value));
</script>

<template>
  <figure :class="['chart', { dim: loading }]">
    <div class="head">
      <ul class="legend">
        <li v-for="line in lines" :key="line.id"><span class="swatch" :style="{ background: line.color }" />{{ line.label }}</li>
      </ul>
      <button type="button" class="chip" :aria-pressed="asTable" @click="asTable = !asTable">
        {{ asTable ? "Show chart" : "Show table" }}
      </button>
    </div>

    <div v-if="!asTable" class="frame">
      <div class="yaxis" aria-hidden="true">
        <span v-for="t in ticks" :key="t" class="ytick" :style="{ bottom: `${(t / top) * 100}%` }">{{ format(t) }}</span>
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
          :aria-label="`${label} over time. Use the left and right arrow keys to read each period.`"
          @pointermove="select"
          @pointerleave="active = null"
          @blur="active = null"
          @keydown="onKey"
        >
          <span v-if="active !== null" class="hover" :style="{ left: `${(active / series.length) * 100}%`, width: `${100 / series.length}%` }" />
          <svg class="lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            <template v-for="item in drawn" :key="item.line.id">
              <polyline
                v-for="(points, p) in item.paths"
                :key="p"
                :points="points"
                fill="none"
                :stroke="item.line.color"
                stroke-width="2"
                stroke-linejoin="round"
                stroke-linecap="round"
                vector-effect="non-scaling-stroke"
              />
            </template>
          </svg>
          <template v-for="item in drawn" :key="item.line.id">
            <span
              v-for="(dot, d) in item.dots"
              :key="d"
              class="dot"
              :style="{ left: `${dot.x}%`, bottom: `${yShare(dot.value)}%`, background: item.line.color }"
            />
          </template>
          <span
            v-for="point in reading"
            :key="point.line.id"
            class="dot ringed"
            :style="{ left: `${point.x}%`, bottom: `${yShare(point.value)}%`, background: point.line.color }"
          />
        </div>
        <p v-if="empty" class="none">{{ emptyText }}</p>
        <div v-if="active !== null" class="tooltip" role="status" :style="tooltipStyle">
          <strong class="when">{{ bucketTitle(series[active]!.bucket, bucket) }}</strong>
          <span v-for="line in lines" :key="line.id" class="line">
            <span class="key" :style="{ background: line.color }" />
            <strong>{{ shown(valueOf(active, line)) }}</strong>{{ " " }}<span class="name">{{ line.label }}</span>
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
          {{ label }} per {{ bucket }}, UTC
        </caption>
        <thead>
          <tr>
            <th scope="col">{{ bucket === "hour" ? "Hour" : "Day" }} (UTC)</th>
            <th v-for="line in lines" :key="line.id" scope="col">{{ line.label }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(point, i) in series" :key="point.bucket">
            <th scope="row">{{ bucketTitle(point.bucket, bucket) }}</th>
            <td v-for="line in lines" :key="line.id">{{ shown(valueOf(i, line)) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </figure>
</template>

<style scoped src="./chart.css"></style>
<style scoped>
/* The lines; the frame around them is chart.css. */
.lines {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
}
.hover {
  position: absolute;
  top: 0;
  bottom: 0;
  background: color-mix(in srgb, var(--text) 6%, transparent);
}
.dot {
  position: absolute;
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  transform: translate(-50%, 50%);
}
/* The point being read: larger, with a ring in the colour of what it sits on. */
.dot.ringed {
  width: 9px;
  height: 9px;
  box-shadow: 0 0 0 2px var(--ring, var(--bg));
}
</style>
