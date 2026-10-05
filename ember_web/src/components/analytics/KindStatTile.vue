<script setup lang="ts">
import { computed } from "vue";
import type { AnalyticsRange, KindTotal, LogKind } from "../../api/LogsClient";
import { KIND_COLORS, KIND_LABELS, RANGE_OPTIONS, describeChange, formatCount } from "../../utils/logAnalytics";
import Sparkline from "./Sparkline.vue";

/** One log kind's headline number for the range, its change against the
 * previous stretch of the same length, and a trend over the range's buckets. */
const props = defineProps<{
  kind: LogKind;
  total: KindTotal;
  /** This kind's count per bucket, oldest first. */
  trend: number[];
  range: AnalyticsRange;
}>();

const change = computed(() => describeChange(props.total.current, props.total.previous));
const arrow = computed(() => ({ up: "▲", down: "▼", flat: "", new: "" })[change.value.direction]);
// More errors is the one change that is bad news.
const bad = computed(() => props.kind === "error" && (change.value.direction === "up" || change.value.direction === "new"));
const since = computed(() => RANGE_OPTIONS.find((o) => o.value === props.range)?.long ?? "");
</script>

<template>
  <div class="tile">
    <span class="label"><span class="key" :style="{ background: KIND_COLORS[kind] }" />{{ KIND_LABELS[kind] }}</span>
    <span class="value">{{ formatCount(total.current) }}</span>
    <span :class="['delta', { bad }]">
      <span v-if="arrow" aria-hidden="true">{{ arrow }}</span>
      {{ change.text }}
      <span class="vs">vs previous {{ since }}</span>
    </span>
    <Sparkline class="trend" :values="trend" :color="KIND_COLORS[kind]" />
  </div>
</template>

<style scoped>
.tile {
  --ring: var(--code-bg);
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 14px 12px;
  border-radius: 10px;
  background: var(--code-bg);
}
.label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8em;
  color: var(--muted);
}
.key {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}
.value {
  font-size: 1.6em;
  font-weight: 600;
  line-height: 1.2;
}
.delta {
  font-size: 0.8em;
  color: var(--text);
}
.delta.bad {
  color: var(--danger);
}
.vs {
  color: var(--muted);
}
.trend {
  position: absolute;
  top: 10px;
  right: 12px;
}
</style>
