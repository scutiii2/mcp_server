<script setup lang="ts">
import { computed } from "vue";
import type { OwnedSpark } from "../../api/EmberlingsClient";
import { useNowSeconds } from "../../composables/useNowSeconds";
import { formatCountdown } from "../../utils/emberlings";
import TierBadge from "./TierBadge.vue";

/** One owned Spark on the Collection tab; a click opens its details. */
const props = defineProps<{ spark: OwnedSpark }>();
const emit = defineEmits<{ open: [] }>();
const now = useNowSeconds();
const faintLeft = computed(() => (props.spark.faint_until === null ? 0 : Math.max(0, props.spark.faint_until - now.value)));
const xpPercent = computed(() =>
  props.spark.xp_needed ? Math.min(100, (props.spark.xp / props.spark.xp_needed) * 100) : 100,
);
</script>

<template>
  <button type="button" class="spark-card" @click="emit('open')">
    <span class="head">
      <span class="spark-name">{{ spark.name }}</span>
      <TierBadge :tier-id="spark.tier_id" />
    </span>
    <span class="meta">Level {{ spark.level }} · {{ spark.copies }} {{ spark.copies === 1 ? "copy" : "copies" }}</span>
    <span v-if="spark.xp_needed !== null" class="xp">
      <span class="xp-track" aria-hidden="true"><span class="xp-fill" :style="{ width: `${xpPercent}%` }" /></span>
      <span class="meta">{{ spark.xp }} / {{ spark.xp_needed }} XP</span>
    </span>
    <span v-else class="meta">Highest level reached</span>
    <span v-if="faintLeft > 0" class="fainted">Fainted · ready in {{ formatCountdown(faintLeft) }}</span>
  </button>
</template>

<style scoped>
.spark-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text);
  background: var(--surface);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.spark-card:hover {
  border-color: var(--accent);
}
.spark-card:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.spark-name {
  font-weight: 600;
}
.meta {
  font-size: 0.85em;
  color: var(--muted);
}
.xp {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.xp-track {
  display: block;
  height: 6px;
  overflow: hidden;
  border-radius: var(--radius-sm);
  background: var(--code-bg);
}
.xp-fill {
  display: block;
  height: 100%;
  background: var(--accent);
}
.fainted {
  font-size: 0.85em;
  color: var(--warning);
}
@media (prefers-reduced-motion: reduce) {
  .spark-card {
    transition: none;
  }
}
</style>
