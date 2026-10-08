<script setup lang="ts">
// The Ember mark: the overview page's flame inside a ring, with one spark
// circling it. Drawn in the accent colour; it flickers like the overview art.
</script>

<template>
  <svg class="ember-logo" viewBox="0 0 64 64" aria-hidden="true">
    <circle class="ring" cx="32" cy="32" r="29" />
    <path class="flame" d="M35 11c3.5 12-10 15-7.5 24 2.5-1.5 4-5 5-7 7 5 12.5 9.5 11 16.5-1 8-7.5 12-14.5 10.5C20 53 18 43 23.5 34.5c-.8 7 2.2 8.5 4 9.5-4.5-13 13-17 7.5-33z" />
    <g class="orbit"><circle class="spark" cx="32" cy="3" r="4" /></g>
  </svg>
</template>

<style scoped>
.ember-logo {
  display: block;
  color: var(--accent);
}
.ring {
  fill: color-mix(in srgb, var(--accent) 8%, transparent);
  stroke: color-mix(in srgb, var(--accent) 35%, transparent);
  stroke-width: 2;
}
.flame {
  fill: currentColor;
  stroke: none;
  transform-origin: 50% 85%;
  animation: logo-flicker 2.6s ease-in-out infinite;
}
.orbit {
  transform-origin: 32px 32px;
  animation: logo-orbit 9s linear infinite;
}
.spark {
  fill: currentColor;
  stroke: none;
}
@keyframes logo-flicker {
  0%, 100% { transform: scale(1); }
  30% { transform: scale(1.04, 1.07); }
  60% { transform: scale(0.98, 1.02); }
}
@keyframes logo-orbit {
  to { transform: rotate(360deg); }
}
@media (prefers-reduced-motion: reduce) {
  .flame, .orbit { animation: none; }
  .orbit { transform: rotate(40deg); }
}
</style>
