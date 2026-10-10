<script setup lang="ts">
/** The page's button. `primary` is copper with a darker bottom edge (one per view),
 * `secondary` the raised steel, `danger` the red-edged destructive one. A disabled
 * button should say why in its own label or next to it. */
withDefaults(defineProps<{ variant?: "primary" | "secondary" | "danger"; type?: "button" | "submit"; disabled?: boolean }>(), {
  variant: "secondary",
  type: "button",
  disabled: false,
});
</script>

<template>
  <button class="em-button" :class="variant" :type="type" :disabled="disabled">
    <slot />
  </button>
</template>

<style scoped>
.em-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--em-space-2);
  min-height: var(--em-target);
  padding: 10px 18px;
  border: 1px solid var(--em-border);
  border-radius: var(--em-radius);
  color: var(--em-text);
  background: var(--em-raised);
  font: inherit;
  font-weight: 600;
  text-align: center;
  cursor: pointer;
  transition: background-color 120ms ease;
}
.em-button:hover:not(:disabled) {
  background: #2f4153;
}
.em-button.primary {
  border-color: var(--em-accent);
  color: var(--em-on-accent);
  background: var(--em-accent);
  box-shadow: 0 3px 0 var(--em-accent-edge);
}
.em-button.primary:hover:not(:disabled) {
  background: #f7c394;
}
.em-button.primary:active:not(:disabled) {
  box-shadow: none;
  transform: translateY(1px);
}
.em-button.danger {
  border-color: var(--em-danger);
  color: var(--em-danger);
  background: var(--em-danger-surface);
}
.em-button:disabled {
  border-color: var(--em-disabled-border);
  color: var(--em-disabled-text);
  background: var(--em-disabled-surface);
  box-shadow: none;
  cursor: default;
}
</style>
