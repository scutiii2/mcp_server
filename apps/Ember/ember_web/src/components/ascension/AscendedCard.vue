<script setup lang="ts">
import { computed } from "vue";
import type { OwnedAscended } from "../../api/AscensionClient";
import { useNowSeconds } from "../../composables/useNowSeconds";
import { useAscensionStore } from "../../stores/ascension";
import { formatCountdown, titleCase } from "../../utils/ascension";
import AscendedTemplateCard from "./AscendedTemplateCard.vue";
import EmBar from "./ui/EmBar.vue";
import EmIcon from "./ui/EmIcon.vue";
import EmTierBadge from "./ui/EmTierBadge.vue";

/** One owned Ascended on the Collection tab: its small card (tier colour, level) with a
 * caption of tier, copies and XP; a click or Enter opens its details. A fainted Ascended
 * is greyed out and says when it is ready again. */
const props = defineProps<{ ascended: OwnedAscended }>();
const emit = defineEmits<{ open: [] }>();
const store = useAscensionStore();
const now = useNowSeconds();
const info = computed(() => store.catalog?.ascendeds.find((s) => s.id === props.ascended.ascended_id) ?? null);
const faintLeft = computed(() => (props.ascended.faint_until === null ? 0 : Math.max(0, props.ascended.faint_until - now.value)));
</script>

<template>
  <div
    class="ascended-card"
    :class="{ down: faintLeft > 0 }"
    role="button"
    tabindex="0"
    :aria-label="`${ascended.name}, ${titleCase(ascended.tier_id)}, level ${ascended.level}`"
    @click="emit('open')"
    @keydown.enter.prevent="emit('open')"
    @keydown.space.prevent="emit('open')"
  >
    <AscendedTemplateCard v-if="info" class="face" :ascended="info" :level="ascended.level" :tier-id="ascended.tier_id" compact show-level />
    <span v-else class="ascended-name">{{ ascended.name }}</span>
    <span class="caption">
      <span class="tier-line">
        <EmTierBadge :tier-id="ascended.tier_id" />
        <span class="copies em-num">{{ ascended.copies }} {{ ascended.copies === 1 ? "copy" : "copies" }}</span>
      </span>
      <span v-if="faintLeft > 0" class="fainted">
        <EmIcon name="clock" /> Fainted, ready in <strong class="em-num">{{ formatCountdown(faintLeft) }}</strong>
      </span>
      <template v-else-if="ascended.xp_needed !== null">
        <EmBar :value="ascended.xp" :max="ascended.xp_needed" :label="`${ascended.name} XP`" />
        <span class="xp em-num">{{ ascended.xp }} / {{ ascended.xp_needed }} XP</span>
      </template>
      <span v-else class="xp">Highest level reached</span>
    </span>
  </div>
</template>

<style scoped>
.ascended-card {
  display: flex;
  flex-direction: column;
  gap: var(--em-space-2);
  width: var(--card-width, 100%);
  border-radius: var(--em-radius);
  color: var(--em-text);
  cursor: pointer;
  transition: filter 120ms ease;
}
.ascended-card:hover {
  filter: brightness(1.1);
}
.ascended-card:focus-visible {
  outline: 2px solid var(--em-accent);
  outline-offset: 3px;
}
.face {
  --card-width: 100%;
}
.ascended-card.down .face {
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
