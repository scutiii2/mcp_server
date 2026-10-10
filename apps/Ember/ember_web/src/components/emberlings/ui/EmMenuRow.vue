<script setup lang="ts">
import EmIcon from "./EmIcon.vue";
import type { IconName } from "./icons";

/** A full-width menu row: icon, label and an arrow. `primary` is the copper one (one
 * per menu), `danger` the red one for a destructive action. */
withDefaults(defineProps<{ icon: IconName; variant?: "primary" | "secondary" | "danger"; disabled?: boolean }>(), {
  variant: "secondary",
  disabled: false,
});
</script>

<template>
  <button type="button" class="em-row" :class="variant" :disabled="disabled">
    <EmIcon :name="icon" :size="20" />
    <span class="label"><slot /></span>
    <EmIcon name="arrow" class="arrow" />
  </button>
</template>

<style scoped>
.em-row {
  display: flex;
  align-items: center;
  gap: var(--em-space-3);
  width: 100%;
  min-height: var(--em-target);
  padding: 10px 18px;
  border: 1px solid var(--em-border);
  border-radius: var(--em-radius);
  color: var(--em-text);
  background: var(--em-raised);
  font: inherit;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
  transition: background-color 120ms ease;
}
.em-row:hover:not(:disabled) {
  background: #2f4153;
}
.label {
  flex: 1;
}
.arrow {
  margin-left: auto;
}
.primary {
  border-color: var(--em-accent);
  color: var(--em-on-accent);
  background: var(--em-accent);
  box-shadow: 0 3px 0 var(--em-accent-edge);
}
.primary:hover:not(:disabled) {
  background: #f7c394;
}
.danger {
  border-color: var(--em-danger);
  color: var(--em-danger);
  background: var(--em-danger-surface);
}
.em-row:disabled {
  border-color: var(--em-disabled-border);
  color: var(--em-disabled-text);
  background: var(--em-disabled-surface);
  box-shadow: none;
  cursor: default;
}
</style>
