<script setup lang="ts">
import { computed } from "vue";
import type { OwnedSpark } from "../../api/EmberlingsClient";
import { useNowSeconds } from "../../composables/useNowSeconds";
import { useEmberlingsStore } from "../../stores/emberlings";
import { formatCountdown, titleCase } from "../../utils/emberlings";
import SparkTemplateCard from "./SparkTemplateCard.vue";

/** One owned Spark on the Collection tab: its small card (tier colour, level)
 * with a caption of tier, copies and XP; a click or Enter opens its details.
 * A fainted Spark is greyed out with a countdown. */
const props = defineProps<{ spark: OwnedSpark }>();
const emit = defineEmits<{ open: [] }>();
const store = useEmberlingsStore();
const now = useNowSeconds();
const info = computed(() => store.catalog?.sparks.find((s) => s.id === props.spark.spark_id) ?? null);
const faintLeft = computed(() => (props.spark.faint_until === null ? 0 : Math.max(0, props.spark.faint_until - now.value)));
const xpPercent = computed(() =>
  props.spark.xp_needed ? Math.min(100, (props.spark.xp / props.spark.xp_needed) * 100) : 100,
);
</script>

<template>
  <div
    class="spark-card"
    :class="{ down: faintLeft > 0 }"
    role="button"
    tabindex="0"
    :aria-label="`${spark.name}, ${titleCase(spark.tier_id)}, level ${spark.level}`"
    @click="emit('open')"
    @keydown.enter.prevent="emit('open')"
    @keydown.space.prevent="emit('open')"
  >
    <SparkTemplateCard v-if="info" class="face" :spark="info" :level="spark.level" :tier-id="spark.tier_id" compact show-level />
    <span v-else class="spark-name">{{ spark.name }}</span>
    <span class="caption">
      <span class="tier-line">{{ titleCase(spark.tier_id) }} · {{ spark.copies }} {{ spark.copies === 1 ? "copy" : "copies" }}</span>
      <span v-if="spark.xp_needed !== null" class="xp">
        <span class="xp-track" aria-hidden="true"><span class="xp-fill" :style="{ width: `${xpPercent}%` }" /></span>
        <span class="meta">{{ spark.xp }} / {{ spark.xp_needed }} XP</span>
      </span>
      <span v-else class="meta">Highest level reached</span>
      <span v-if="faintLeft > 0" class="fainted">Fainted · ready in {{ formatCountdown(faintLeft) }}</span>
    </span>
  </div>
</template>

<style scoped>
.spark-card {
  --card-width: 180px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: var(--card-width);
  border-radius: var(--radius-lg);
  color: var(--text);
  cursor: pointer;
  transition: filter 0.15s ease;
}
.spark-card:hover {
  filter: brightness(1.1);
}
.spark-card:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 4px;
}
.spark-card.down .face {
  filter: grayscale(1);
  opacity: 0.7;
}
.caption {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 0 2px;
}
.tier-line {
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
  height: 5px;
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
