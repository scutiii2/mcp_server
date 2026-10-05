<script setup lang="ts">
/** One number of the Admin overview, with a small label above it. `value` is
 * null while the count loads. `warn` colours it for counts that want attention. */
defineProps<{ label: string; value: number | null; warn?: boolean }>();
</script>

<template>
  <div class="tile">
    <span class="label">{{ label }}</span>
    <span :class="['value', { warn: warn && value }]">{{ value ?? "–" }}</span>
  </div>
</template>

<style scoped>
.tile {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--code-bg);
}
.label {
  font-size: 0.8em;
  color: var(--muted);
}
.value {
  font-size: 1.6em;
  font-weight: 600;
  line-height: 1.2;
}
.value.warn {
  color: var(--danger);
}
</style>
