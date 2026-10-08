<script setup lang="ts">
import { computed } from "vue";
import type { AnalyticsRange, KindTotal, LogKind } from "../../api/LogsClient";
import { KIND_COLORS, KIND_LABELS, RANGE_OPTIONS, describeChange, formatCount } from "../../utils/logAnalytics";
import StatTile from "./StatTile.vue";

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
// More errors is the one change that is bad news.
const bad = computed(() => props.kind === "error" && (change.value.direction === "up" || change.value.direction === "new"));
const since = computed(() => RANGE_OPTIONS.find((o) => o.value === props.range)?.long ?? "");
</script>

<template>
  <StatTile
    :label="KIND_LABELS[kind]"
    :value="formatCount(total.current)"
    :change="change"
    :bad="bad"
    :since="since"
    :trend="trend"
    :color="KIND_COLORS[kind]"
  />
</template>
