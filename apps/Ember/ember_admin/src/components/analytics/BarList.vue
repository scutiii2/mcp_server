<script setup lang="ts" generic="K extends string | number">
import { computed } from "vue";
import { formatCount } from "../../utils/logAnalytics";

/** Horizontal bars for a short ranking (top sources, busiest accounts): one
 * colour, since the rows are one series; the value sits at the bar's tip.
 * `selectable` rows are buttons that emit their key. */
const props = defineProps<{
  items: { key: K; label: string; count: number }[];
  color: string;
  selectable?: boolean;
  emptyText?: string;
  /** How a row's value is written at its bar's tip (counts by default). */
  format?: (value: number) => string;
}>();
const emit = defineEmits<{ select: [key: K] }>();

const peak = computed(() => Math.max(1, ...props.items.map((i) => i.count)));
</script>

<template>
  <p v-if="items.length === 0" class="empty">{{ emptyText ?? "Nothing in this range." }}</p>
  <ul v-else class="list">
    <li v-for="item in items" :key="item.key">
      <component
        :is="selectable ? 'button' : 'div'"
        :type="selectable ? 'button' : undefined"
        :class="['row', { selectable }]"
        :title="item.label"
        @click="selectable && emit('select', item.key)"
      >
        <span class="label">{{ item.label }}</span>
        <span class="track">
          <span class="bar" :style="{ '--share': item.count / peak, background: color }" />
          <span class="value">{{ (format ?? formatCount)(item.count) }}</span>
        </span>
      </component>
    </li>
  </ul>
</template>

<style scoped>
.list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.row {
  display: grid;
  grid-template-columns: minmax(0, 38%) minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 4px 6px;
  border: 0;
  border-radius: var(--radius-md);
  background: none;
  color: var(--text);
  font: inherit;
  font-size: 0.85em;
  text-align: left;
}
.row.selectable {
  cursor: pointer;
}
.row.selectable:hover,
.row.selectable:focus-visible {
  background: color-mix(in srgb, var(--text) 6%, transparent);
}
.label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--mono);
  font-size: 0.95em;
}
.track {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.bar {
  flex: none;
  width: max(2px, calc((100% - 3.4em) * var(--share)));
  height: 8px;
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
.value {
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.empty {
  margin: 0;
  color: var(--muted);
  font-size: 0.85em;
}
</style>
