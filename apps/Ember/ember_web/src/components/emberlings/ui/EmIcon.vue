<script setup lang="ts">
import { computed } from "vue";
import { ICONS, type IconName } from "./icons";

/** One of the page's icons, drawn in the surrounding text colour. Decorative:
 * the meaning is always also written as text. */
const props = withDefaults(defineProps<{ name: IconName; size?: number }>(), { size: 18 });
const path = computed(() => ICONS[props.name] ?? ICONS.spark);
</script>

<template>
  <svg class="em-icon" :width="size" :height="size" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path :d="path" />
  </svg>
</template>

<style scoped>
.em-icon {
  flex: none;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linejoin: miter;
  stroke-linecap: square;
}
</style>
