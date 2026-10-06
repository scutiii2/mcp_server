<script setup lang="ts">
import { computed, ref, useTemplateRef } from "vue";
import { axisLabel, bucketTitle, formatCount, niceCeil, type BucketSize } from "../../utils/logAnalytics";
import { useBucketCursor, type ChartPart } from "./useBucketCursor";

/** Counts over time: one stacked column per bucket, a segment per part (bottom to
 * top in `parts` order). Hover, or the arrow keys once it has focus, reads a bucket
 * in one tooltip for every part; the table twin shows the same numbers without
 * either. Buckets are UTC. Used for log entries and for requests by status class. */
const props = withDefaults(
  defineProps<{
    series: { bucket: string; counts: Partial<Record<string, number>> }[];
    parts: ChartPart[];
    bucket: BucketSize;
    /** What is counted, in the plural: names the chart for screen readers and the empty state. */
    noun?: string;
    /** Refetching: keep the last render, dimmed. */
    loading?: boolean;
  }>(),
  { noun: "entries" },
);

const plot = useTemplateRef<HTMLElement>("plot");
const { active, labelEvery, tooltipStyle, select, onKey } = useBucketCursor(plot, () => props.series.length);
const asTable = ref(false);

const countOf = (index: number, part: ChartPart) => props.series[index]?.counts[part.id] ?? 0;
const totalOf = (index: number) => props.parts.reduce((sum, part) => sum + countOf(index, part), 0);

const top = computed(() => niceCeil(Math.max(0, ...props.series.map((_, i) => totalOf(i)))));
const empty = computed(() => props.series.every((_, i) => totalOf(i) === 0));
const columns = computed(() =>
  props.series.map((_, i) => {
    const segments = props.parts.filter((part) => countOf(i, part) > 0).map((part) => ({ part, count: countOf(i, part) }));
    return { height: (totalOf(i) / top.value) * 100, segments };
  }),
);
const ticks = computed(() => [top.value, top.value / 2, 0]);
const heading = computed(() => props.noun.charAt(0).toUpperCase() + props.noun.slice(1));
</script>

<template>
  <figure :class="['chart', { dim: loading }]">
    <div class="head">
      <ul class="legend">
        <li v-for="part in parts" :key="part.id"><span class="swatch" :style="{ background: part.color }" />{{ part.label }}</li>
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
          class="plot columns"
          role="group"
          tabindex="0"
          :aria-label="`${heading} over time. Use the left and right arrow keys to read each period.`"
          @pointermove="select"
          @pointerleave="active = null"
          @blur="active = null"
          @keydown="onKey"
        >
          <div v-for="(column, i) in columns" :key="series[i]!.bucket" :class="['col', { active: active === i }]">
            <div class="stack" :style="{ height: `${column.height}%` }">
              <span
                v-for="(segment, s) in column.segments"
                :key="segment.part.id"
                :class="['seg', { cap: s === column.segments.length - 1 }]"
                :style="{ flexGrow: segment.count, background: segment.part.color }"
              />
            </div>
          </div>
        </div>
        <p v-if="empty" class="none">No {{ noun }} in this range.</p>
        <div v-if="active !== null" class="tooltip" role="status" :style="tooltipStyle">
          <strong class="when">{{ bucketTitle(series[active]!.bucket, bucket) }}</strong>
          <span v-for="part in parts" :key="part.id" class="line">
            <span class="key" :style="{ background: part.color }" />
            <strong>{{ countOf(active, part).toLocaleString() }}</strong>{{ " " }}<span class="name">{{ part.label }}</span>
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
          {{ heading }} per {{ bucket }}, UTC
        </caption>
        <thead>
          <tr>
            <th scope="col">{{ bucket === "hour" ? "Hour" : "Day" }} (UTC)</th>
            <th v-for="part in parts" :key="part.id" scope="col">{{ part.label }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(point, i) in series" :key="point.bucket">
            <th scope="row">{{ bucketTitle(point.bucket, bucket) }}</th>
            <td v-for="part in parts" :key="part.id">{{ countOf(i, part).toLocaleString() }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </figure>
</template>

<style scoped src="./chart.css"></style>
<style scoped>
/* The stacked columns; the frame around them is chart.css. */
.columns {
  display: flex;
  align-items: flex-end;
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
</style>
