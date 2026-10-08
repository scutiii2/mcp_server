<script setup lang="ts">
import { computed } from "vue";

/** A small ring that empties as `remaining` seconds run down from `total`. */
const props = defineProps<{ remaining: number; total: number }>();

const RADIUS = 15;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const offset = computed(() => CIRCUMFERENCE * (1 - (props.total > 0 ? Math.max(0, Math.min(props.remaining / props.total, 1)) : 0)));
</script>

<template>
  <svg class="ring" viewBox="0 0 36 36" width="28" height="28" aria-hidden="true">
    <circle cx="18" cy="18" :r="RADIUS" fill="none" stroke="var(--surface)" stroke-width="4" />
    <circle
      class="arc"
      cx="18"
      cy="18"
      :r="RADIUS"
      fill="none"
      stroke="var(--accent)"
      stroke-width="4"
      stroke-linecap="round"
      :stroke-dasharray="CIRCUMFERENCE"
      :stroke-dashoffset="offset"
      transform="rotate(-90 18 18)"
    />
  </svg>
</template>

<style scoped>
.arc {
  transition: stroke-dashoffset 1s linear;
}
@media (prefers-reduced-motion: reduce) {
  .arc {
    transition: none;
  }
}
</style>
