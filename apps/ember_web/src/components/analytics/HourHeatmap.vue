<script setup lang="ts">
import { computed } from "vue";
import type { AnalyticsReport } from "../../api/LogsClient";
import { WEEKDAYS, buildHourHeatmap } from "../../utils/logAnalytics";

/** When entries happen: weekday (rows, Sunday first) by hour (columns), darker
 * for more. UTC, like ember_api's buckets. */
const props = defineProps<{ cells: AnalyticsReport["heatmap"] }>();

const rows = computed(() => buildHourHeatmap(props.cells));
const HOUR_TICKS = [0, 6, 12, 18];
const pad = (hour: number) => String(hour).padStart(2, "0");
</script>

<template>
  <div class="heat">
    <div class="grid" role="img" aria-label="Entries by weekday and hour of day, in UTC">
      <div class="row ticks" aria-hidden="true">
        <span class="day" />
        <span v-for="h in HOUR_TICKS" :key="h" class="tick" :style="{ gridColumn: `${h + 2} / span 3` }">{{ pad(h) }}</span>
      </div>
      <div v-for="(row, weekday) in rows" :key="weekday" class="row">
        <span class="day">{{ WEEKDAYS[weekday] }}</span>
        <span
          v-for="cell in row"
          :key="cell.hour"
          :class="['cell', `level-${cell.level}`]"
          :title="`${WEEKDAYS[cell.weekday]} ${pad(cell.hour)}:00 UTC: ${cell.count.toLocaleString()} ${cell.count === 1 ? 'entry' : 'entries'}`"
        />
      </div>
    </div>
    <div class="legend" aria-hidden="true">
      Less
      <span v-for="level in [0, 1, 2, 3, 4]" :key="level" :class="['cell', `level-${level}`]" />
      More
      <span class="utc">hours in UTC</span>
    </div>
  </div>
</template>

<style scoped>
.heat {
  min-width: 0;
}
.grid {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.row {
  display: grid;
  grid-template-columns: 2.6em repeat(24, minmax(0, 1fr));
  gap: 2px;
  align-items: center;
}
.day,
.tick {
  font-size: 0.72em;
  color: var(--muted);
}
.cell {
  aspect-ratio: 1;
  max-height: 22px;
  border-radius: 2px;
  background: var(--code-bg);
}
.cell.level-1 {
  background: color-mix(in srgb, var(--kind-action) 28%, var(--code-bg));
}
.cell.level-2 {
  background: color-mix(in srgb, var(--kind-action) 50%, var(--code-bg));
}
.cell.level-3 {
  background: color-mix(in srgb, var(--kind-action) 75%, var(--code-bg));
}
.cell.level-4 {
  background: var(--kind-action);
}
.cell:hover {
  outline: 2px solid var(--text);
  outline-offset: -1px;
}
.legend {
  display: flex;
  align-items: center;
  gap: 3px;
  margin-top: 8px;
  font-size: 0.75em;
  color: var(--muted);
}
.legend .cell {
  width: 11px;
  height: 11px;
}
.utc {
  margin-left: auto;
}
</style>
