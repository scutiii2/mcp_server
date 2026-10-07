<script setup lang="ts">
import { RouterLink } from "vue-router";

/** The "Open page" button on an extension tile and a capability card: an
 * outlined link, not bare text. `external` opens the target in a new tab and
 * shows an up-right arrow; otherwise it is an in-app route with a right arrow.
 * Below 480px only the arrow stays; the label remains for screen readers. */
defineProps<{ to: string; external?: boolean }>();
</script>

<template>
  <a v-if="external" class="open-page" :href="to" target="_blank" rel="noopener noreferrer">
    <span class="label">Open page</span>
    <svg class="arrow" viewBox="0 0 16 16" aria-hidden="true"><path d="M5 11 11 5M6 5h5v5" /></svg>
  </a>
  <RouterLink v-else class="open-page" :to="to" @click.stop>
    <span class="label">Open page</span>
    <svg class="arrow" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4" /></svg>
  </RouterLink>
</template>

<style scoped>
.open-page {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg);
  color: var(--text);
  font-size: 0.85rem;
  line-height: 1.4;
  text-decoration: none;
  white-space: nowrap;
}
.open-page:hover {
  border-color: var(--accent);
}
.open-page:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.arrow {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: var(--accent);
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}
@media (max-width: 480px) {
  .label {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
  .open-page {
    padding: 6px;
  }
}
</style>
