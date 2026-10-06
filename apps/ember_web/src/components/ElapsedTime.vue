<script setup lang="ts">
import { toRef } from "vue";
import { useElapsed } from "../composables/useElapsed";
import { formatClock } from "../utils/usageFormat";

// A running clock: how long it has been since `since` (a Date.now() value).
const props = defineProps<{ since: number }>();
const elapsed = useElapsed(toRef(props, "since"));
</script>

<template>
  <span class="clock">{{ formatClock(elapsed) }}</span>
</template>

<style scoped>
.clock {
  font-variant-numeric: tabular-nums;
}
</style>
