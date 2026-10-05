<script setup lang="ts">
import { computed } from "vue";

/** A small trend line: 2px line, a 10% wash under it, and the latest value as a
 * dot with a surface ring (`--ring`, the colour of whatever it sits on). Purely
 * decorative: the number it summarises is always written next to it. */
const props = defineProps<{ values: number[]; color: string }>();

const WIDTH = 96;
const HEIGHT = 28;
const PAD = 5; // room for the end dot and its ring

const points = computed(() => {
  const { values } = props;
  const peak = Math.max(1, ...values);
  const step = values.length > 1 ? (WIDTH - 2 * PAD) / (values.length - 1) : 0;
  return values.map((v, i): [number, number] => [
    values.length > 1 ? PAD + i * step : WIDTH / 2,
    HEIGHT - PAD - (v / peak) * (HEIGHT - 2 * PAD),
  ]);
});
const line = computed(() => points.value.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" "));
const area = computed(() => {
  const first = points.value[0];
  const last = points.value.at(-1);
  if (!first || !last) return "";
  return `M${first[0]},${HEIGHT - PAD} L${line.value.replaceAll(" ", " L")} L${last[0]},${HEIGHT - PAD} Z`;
});
const end = computed(() => points.value.at(-1));
</script>

<template>
  <svg class="spark" :width="WIDTH" :height="HEIGHT" :viewBox="`0 0 ${WIDTH} ${HEIGHT}`" aria-hidden="true">
    <path v-if="points.length > 1" :d="area" :fill="color" fill-opacity="0.1" />
    <polyline
      v-if="points.length > 1"
      :points="line"
      fill="none"
      :stroke="color"
      stroke-width="2"
      stroke-linejoin="round"
      stroke-linecap="round"
    />
    <circle v-if="end" :cx="end[0]" :cy="end[1]" r="4" :fill="color" stroke="var(--ring, var(--bg))" stroke-width="2" />
  </svg>
</template>

<style scoped>
.spark {
  display: block;
  overflow: visible;
}
</style>
