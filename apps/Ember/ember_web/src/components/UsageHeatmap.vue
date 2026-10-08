<script setup lang="ts">
import { computed, ref } from "vue";
import { buildHeatmap, type HeatDay } from "../utils/usageHeatmap";

// The last 12 months as a grid of days, one column per week (Sunday first),
// darker for more tokens. Days are UTC days, as ember_api counts them. Hover a
// day to see its tokens.
const props = defineProps<{
  daily: { date: string; tokens: number }[];
  /** Today as a UTC day, "YYYY-MM-DD". */
  today: string;
}>();

const weeks = computed(() => buildHeatmap(props.daily, props.today));
// Keep the date, so refreshed data also updates the hovered day's count.
const hovered = ref<string | null>(null);
const active = computed<HeatDay | null>(() => {
  if (hovered.value === null) return null;
  return weeks.value.flat().find((day) => day.date === hovered.value) ?? null;
});
const tokensText = (day: HeatDay) => `${day.tokens.toLocaleString()} ${day.tokens === 1 ? "token" : "tokens"}`;
</script>

<template>
  <div class="heatmap-wrap">
    <div class="scroll">
      <div class="heatmap" role="group" aria-label="Daily token usage over the last 12 months, in UTC">
        <div v-for="week in weeks" :key="week[0]!.date" class="week">
          <span
            v-for="day in week"
            :key="day.date"
            :class="['cell', day.level === null ? 'future' : `level-${day.level}`]"
            :aria-label="day.level === null ? undefined : `${day.date}: ${tokensText(day)}`"
            @pointerenter="day.level !== null && (hovered = day.date)"
            @pointerleave="hovered = null"
          />
        </div>
      </div>
    </div>
    <div class="cell-details" role="status" aria-live="polite" aria-atomic="true">
      <template v-if="active"><strong>{{ active.date }}</strong><span>{{ tokensText(active) }}</span></template>
      <span v-else>Hover a day to see its usage.</span>
    </div>
    <div class="legend" aria-hidden="true">
      Less
      <span v-for="level in [0, 1, 2, 3, 4]" :key="level" :class="['cell', `level-${level}`]" />
      More
    </div>
  </div>
</template>

<style scoped>
.scroll {
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
.heatmap .cell:not(.future):hover {
  outline: 2px solid var(--text);
  outline-offset: -1px;
}
.cell-details {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 12px;
  min-height: 32px;
  margin-top: 8px;
  color: var(--muted);
  font-size: 0.8em;
}
.cell-details strong {
  color: var(--text);
  font-weight: 600;
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
