<script setup lang="ts">
import EmIcon from "./EmIcon.vue";

/** A short notice with an icon: `warning` (gold) or `error` (red). The text is the
 * message; the colour only backs it up. */
withDefaults(defineProps<{ tone?: "warning" | "error" }>(), { tone: "warning" });
</script>

<template>
  <div class="em-notice" :class="tone" :role="tone === 'error' ? 'alert' : 'status'">
    <EmIcon :name="tone === 'error' ? 'warning' : 'clock'" />
    <span><slot /></span>
  </div>
</template>

<style scoped>
.em-notice {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border: 1px solid var(--em-warning);
  border-radius: var(--em-radius);
  color: var(--em-warning);
  background: var(--em-warning-surface);
  font-size: 13px;
}
.em-notice.error {
  border-color: var(--em-danger);
  color: var(--em-danger);
  background: var(--em-danger-surface);
}
</style>
