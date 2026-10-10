<script setup lang="ts">
import { computed } from "vue";
import type { OwnedSpark } from "../../api/EmberlingsClient";
import { useNowSeconds } from "../../composables/useNowSeconds";
import { useEmberlingsStore } from "../../stores/emberlings";
import { formatCountdown, titleCase } from "../../utils/emberlings";
import SparkTemplateCard from "./SparkTemplateCard.vue";
import EmBar from "./ui/EmBar.vue";
import EmIcon from "./ui/EmIcon.vue";
import EmTierBadge from "./ui/EmTierBadge.vue";

/** One owned Spark on the Collection tab: its small card (tier colour, level) with a
 * caption of tier, copies and XP; a click or Enter opens its details. A fainted Spark
 * is greyed out and says when it is ready again. */
const props = defineProps<{ spark: OwnedSpark }>();
const emit = defineEmits<{ open: [] }>();
const store = useEmberlingsStore();
const now = useNowSeconds();
const info = computed(() => store.catalog?.sparks.find((s) => s.id === props.spark.spark_id) ?? null);
const faintLeft = computed(() => (props.spark.faint_until === null ? 0 : Math.max(0, props.spark.faint_until - now.value)));
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
      <span class="tier-line">
        <EmTierBadge :tier-id="spark.tier_id" />
        <span class="copies em-num">{{ spark.copies }} {{ spark.copies === 1 ? "copy" : "copies" }}</span>
      </span>
      <span v-if="faintLeft > 0" class="fainted">
        <EmIcon name="clock" /> Fainted, ready in <strong class="em-num">{{ formatCountdown(faintLeft) }}</strong>
      </span>
      <template v-else-if="spark.xp_needed !== null">
        <EmBar :value="spark.xp" :max="spark.xp_needed" :label="`${spark.name} XP`" />
        <span class="xp em-num">{{ spark.xp }} / {{ spark.xp_needed }} XP</span>
      </template>
      <span v-else class="xp">Highest level reached</span>
    </span>
  </div>
</template>

<style scoped>
.spark-card {
  display: flex;
  flex-direction: column;
  gap: var(--em-space-2);
  width: var(--card-width, 100%);
  border-radius: var(--em-radius);
  color: var(--em-text);
  cursor: pointer;
  transition: filter 120ms ease;
}
.spark-card:hover {
  filter: brightness(1.1);
}
.spark-card:focus-visible {
  outline: 2px solid var(--em-accent);
  outline-offset: 3px;
}
.face {
  --card-width: 100%;
}
.spark-card.down .face {
  filter: grayscale(1);
  opacity: 0.72;
}
.caption {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.tier-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 8px;
}
.copies,
.xp {
  font-size: 12px;
  color: var(--em-muted);
}
.fainted {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--em-danger);
}
</style>
