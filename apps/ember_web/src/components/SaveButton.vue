<script setup lang="ts">
// A save / saved toggle button with a heart: a light card with a faint heart
// while not saved, an inverted (text-on-background) card with a solid heart once
// saved. It only shows the state; the parent owns it and reacts to @click.
// `small` shrinks it for a row of icon actions. Attributes (title, disabled,
// @click ...) fall through to the button.
withDefaults(defineProps<{ saved: boolean; label?: string; savedLabel?: string; small?: boolean }>(), {
  label: "Save",
  savedLabel: "Saved",
});
</script>

<template>
  <button type="button" :class="['save-button', { saved, small }]" :aria-pressed="saved">
    {{ saved ? savedLabel : label }}
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <path
        d="M12 21s-7.5-4.6-9.5-9.2C1.2 8.6 3 5 6.5 5c2 0 3.5 1.1 5.5 3.2C14 6.1 15.5 5 17.5 5 21 5 22.8 8.6 21.5 11.8 19.5 16.4 12 21 12 21z"
      />
    </svg>
  </button>
</template>

<style scoped>
.save-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 16px;
  border: 1px solid var(--border);
  border-radius: 10px;
  cursor: pointer;
  font: inherit;
  font-size: 0.9em;
  font-weight: 600;
  color: var(--text);
  background: var(--surface);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15);
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}
.save-button svg {
  fill: color-mix(in srgb, var(--muted) 45%, var(--surface));
  transition: fill 0.15s ease, transform 0.15s ease;
}
.save-button:hover:not(:disabled) {
  border-color: var(--accent);
}
.save-button.saved {
  color: var(--bg);
  border-color: var(--text);
  background: var(--text);
}
.save-button.saved svg {
  fill: currentColor;
  transform: scale(1.1);
}
.save-button.small {
  gap: 4px;
  padding: 2px 10px;
  border-radius: 8px;
  font-size: 0.78em;
  box-shadow: none;
}
.save-button.small svg {
  width: 12px;
  height: 12px;
}
.save-button:disabled {
  cursor: default;
  opacity: 0.6;
}
.save-button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>
