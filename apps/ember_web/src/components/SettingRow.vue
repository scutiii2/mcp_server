<script setup lang="ts">
/** One setting on the Settings page: its name and description on the left, its
 * control (the default slot) on the right. A setting that differs from its
 * default (`modified`) gets an accent dot and a reset button; the parent owns
 * the value and puts it back on `reset`. `settingId` is what the search jumps to. */
defineProps<{ settingId: string; label: string; description?: string; modified?: boolean }>();
const emit = defineEmits<{ reset: [] }>();
</script>

<template>
  <div class="setting" :data-setting-id="settingId">
    <div class="text">
      <div class="label">
        <span v-if="modified" class="dot" aria-hidden="true" />
        <span>{{ label }}</span>
        <span v-if="modified" class="sr-only">(changed from the default)</span>
      </div>
      <p v-if="description" class="description">{{ description }}</p>
    </div>
    <div class="control">
      <slot />
      <button
        v-if="modified"
        type="button"
        class="reset"
        title="Back to default"
        :aria-label="`Reset ${label} to its default`"
        @click="emit('reset')"
      >
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
          <path d="M3 3v5h5" />
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.setting {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 16px;
  padding: 10px 0;
  border-top: 1px solid var(--border);
}
.setting:first-of-type {
  border-top: none;
}
.text {
  flex: 1 1 220px;
  min-width: 0;
}
.label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--accent);
}
.description {
  margin: 2px 0 0;
  font-size: 0.85em;
  color: var(--muted);
}
.control {
  display: flex;
  align-items: center;
  gap: 8px;
}
.reset {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  cursor: pointer;
  color: var(--muted);
  background: var(--bg);
}
.reset:hover,
.reset:focus-visible {
  color: var(--text);
  border-color: var(--accent);
}
.reset svg {
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
</style>
