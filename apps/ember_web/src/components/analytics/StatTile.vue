<script setup lang="ts">
import { computed } from "vue";
import type { Change } from "../../utils/logAnalytics";
import Sparkline from "./Sparkline.vue";

/** A headline number for a range, its change against the previous stretch of the
 * same length, and (optionally) a trend over the range's buckets. The colour
 * names the series it belongs to; a tile for bad news (more errors) is marked
 * with `bad`. Callers format the value and work out the change. */
const props = defineProps<{
  label: string;
  /** Already formatted: "1.2K", "3.4%", "250 ms". */
  value: string;
  change: Change;
  bad?: boolean;
  /** "24 hours", "7 days": the length of the previous period compared with. */
  since: string;
  /** The series' value per bucket, oldest first; no trend line without it. */
  trend?: number[];
  color: string;
}>();

const arrow = computed(() => ({ up: "▲", down: "▼", flat: "", new: "" })[props.change.direction]);
</script>

<template>
  <div class="tile">
    <span class="label"><span class="key" :style="{ background: color }" />{{ label }}</span>
    <span class="value">{{ value }}</span>
    <span :class="['delta', { bad }]">
      <span v-if="arrow" aria-hidden="true">{{ arrow }}</span>
      {{ change.text }}
      <span class="vs">vs previous {{ since }}</span>
    </span>
    <Sparkline v-if="trend" class="trend" :values="trend" :color="color" />
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
