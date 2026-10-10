<script setup lang="ts">
import { computed } from "vue";

/** A progress bar with its value written next to it: XP (copper) or HP (green,
 * red below 30 percent). Exposed as a progressbar with an accessible name. */
const props = defineProps<{ value: number; max: number; label: string; kind?: "xp" | "hp" }>();
const percent = computed(() => (props.max > 0 ? Math.min(100, Math.max(0, (props.value / props.max) * 100)) : 0));
const low = computed(() => props.kind === "hp" && percent.value < 30);
</script>

<template>
  <div
    class="em-bar"
    :class="[kind ?? 'xp', { low }]"
    role="progressbar"
    :aria-label="label"
    aria-valuemin="0"
    :aria-valuemax="max"
    :aria-valuenow="value"
  >
    <span class="fill" :style="{ width: `${percent}%` }" />
  </div>
</template>

<style scoped>
.em-bar {
  height: 6px;
  overflow: hidden;
  border: 1px solid var(--em-disabled-border);
  border-radius: var(--em-radius);
  background: var(--em-bg);
}
.em-bar.hp {
  height: 12px;
}
.fill {
  display: block;
  height: 100%;
  background: var(--em-accent);
  transition: width 220ms ease;
}
.hp .fill {
  background: var(--em-success);
}
.hp.low .fill {
  background: var(--em-danger);
}
</style>
