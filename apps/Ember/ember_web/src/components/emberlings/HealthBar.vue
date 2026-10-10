<script setup lang="ts">
import { computed } from "vue";

/** A fighter's health as a meter, with the numbers written beside it. */
const props = defineProps<{ hp: number; maxHp: number; label: string }>();
const percent = computed(() => (props.maxHp > 0 ? Math.max(0, Math.min(100, (props.hp / props.maxHp) * 100)) : 0));
const low = computed(() => percent.value <= 25);
</script>

<template>
  <div class="health-bar">
    <div class="track" role="meter" :aria-label="label" aria-valuemin="0" :aria-valuemax="maxHp" :aria-valuenow="hp">
      <div class="fill" :class="{ low }" :style="{ width: `${percent}%` }" />
    </div>
    <span class="numbers">{{ hp }} / {{ maxHp }} HP</span>
  </div>
</template>

<style scoped>
.health-bar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.track {
  flex: 1;
  height: 10px;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--code-bg);
}
.fill {
  height: 100%;
  background: var(--success);
  transition: width 0.15s ease;
}
.fill.low {
  background: var(--danger);
}
.numbers {
  font-size: 0.85em;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  color: var(--muted);
}
@media (prefers-reduced-motion: reduce) {
  .fill {
    transition: none;
  }
}
</style>
