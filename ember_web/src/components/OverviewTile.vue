<script setup lang="ts">
import { RouterLink } from "vue-router";

/** One tile of the Overview page: a card with the page's icon over a soft
 * accent blob and bubbles, and its name underneath. The description is the
 * hover / long-press tooltip. `icon` is SVG path data (24x24). */
defineProps<{ to: string; label: string; description: string; icon: string[] }>();
</script>

<template>
  <RouterLink :to="to" class="tile" :title="description">
    <span class="art" aria-hidden="true">
      <svg class="blob" viewBox="0 0 120 80">
        <path d="M18 44c-6-16 8-32 28-34 14-2 22 6 36 4 18-3 30 12 24 28-5 14-20 22-38 20-12-1-18 5-30 0-10-4-16-9-20-18z" />
        <circle cx="10" cy="18" r="3.5" />
        <circle cx="22" cy="8" r="2" />
        <circle cx="110" cy="14" r="5" />
        <circle cx="102" cy="30" r="2.5" />
        <circle cx="8" cy="62" r="4" />
      </svg>
      <svg class="icon" viewBox="0 0 24 24">
        <path v-for="d in icon" :key="d" :d="d" />
      </svg>
    </span>
    <span class="label">{{ label }}</span>
  </RouterLink>
</template>

<style scoped>
.tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 18px 10px 16px;
  border-radius: 12px;
  color: var(--text);
  background: var(--surface);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.14);
  text-align: center;
  text-decoration: none;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.tile:hover,
.tile:focus-visible {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.2);
}
.tile:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.art {
  position: relative;
  display: grid;
  place-items: center;
  width: 100%;
  max-width: 120px;
}
.blob {
  width: 100%;
  height: auto;
}
.blob path {
  fill: color-mix(in srgb, var(--accent) 16%, transparent);
}
.blob circle {
  fill: none;
  stroke: color-mix(in srgb, var(--accent) 45%, transparent);
  stroke-width: 1.6;
}
.icon {
  position: absolute;
  width: 40px;
  height: 40px;
  fill: color-mix(in srgb, var(--accent) 30%, transparent);
  stroke: var(--accent);
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.label {
  font-size: 0.9em;
  font-weight: 500;
}
</style>
