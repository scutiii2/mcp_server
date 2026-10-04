<script setup lang="ts">
import { computed } from "vue";
import { buildHeatmap } from "../utils/usageHeatmap";

// The last 12 months as a grid of days, one column per week (Sunday first),
// darker for more tokens. Days are UTC days, as ember_api counts them.
const props = defineProps<{
  daily: { date: string; tokens: number }[];
  /** Today as a UTC day, "YYYY-MM-DD". */
  today: string;
}>();

const weeks = computed(() => buildHeatmap(props.daily, props.today));
</script>

<template>
  <div class="heatmap-wrap">
    <div class="heatmap" role="img" aria-label="Daily token usage over the last 12 months">
      <div v-for="week in weeks" :key="week[0]!.date" class="week">
        <span
          v-for="day in week"
          :key="day.date"
          :class="['cell', day.level === null ? 'future' : `level-${day.level}`]"
          :title="day.level === null ? undefined : `${day.date}: ${day.tokens.toLocaleString()} tokens`"
        />
      </div>
    </div>
    <div class="legend" aria-hidden="true">
      Less
      <span v-for="level in [0, 1, 2, 3, 4]" :key="level" :class="['cell', `level-${level}`]" />
      More
    </div>
  </div>
</template>

<style scoped>
.heatmap-wrap {
  overflow-x: auto;
}
.heatmap {
  display: flex;
  gap: 3px;
  width: max-content;
}
.week {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.cell {
  width: 11px;
  height: 11px;
  border-radius: 2px;
  background: var(--code-bg);
}
.cell.future {
  background: transparent;
}
.cell.level-1 {
  background: color-mix(in srgb, var(--accent) 28%, var(--code-bg));
}
.cell.level-2 {
  background: color-mix(in srgb, var(--accent) 50%, var(--code-bg));
}
.cell.level-3 {
  background: color-mix(in srgb, var(--accent) 75%, var(--code-bg));
}
.cell.level-4 {
  background: var(--accent);
}
.legend {
  display: flex;
  align-items: center;
  gap: 3px;
  margin-top: 8px;
  font-size: 0.75em;
  color: var(--muted);
}
</style>
