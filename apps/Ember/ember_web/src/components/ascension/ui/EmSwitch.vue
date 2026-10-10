<script setup lang="ts">
/** A squared on/off switch with its label. The whole row is the 44 px target. */
defineProps<{ modelValue: boolean; label: string; disabled?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: boolean] }>();
</script>

<template>
  <label class="em-switch" :class="{ disabled }">
    <input
      type="checkbox"
      role="switch"
      class="input"
      :checked="modelValue"
      :disabled="disabled"
      @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked)"
    />
    <span class="track" aria-hidden="true"><span class="thumb" /></span>
    <span class="label">{{ label }}</span>
    <slot />
  </label>
</template>

<style scoped>
.em-switch {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--em-space-3);
  min-height: var(--em-target);
  cursor: pointer;
}
.em-switch.disabled {
  cursor: default;
  opacity: 0.7;
}
.input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  opacity: 0;
  cursor: inherit;
}
.track {
  display: inline-flex;
  flex: none;
  align-items: center;
  width: 40px;
  height: 24px;
  padding: 3px;
  border: 1px solid var(--em-border);
  border-radius: var(--em-radius);
  background: var(--em-bg);
}
.thumb {
  width: 16px;
  height: 16px;
  background: var(--em-muted);
}
.input:checked + .track {
  justify-content: flex-end;
  border-color: var(--em-accent);
  background: #694728;
}
.input:checked + .track .thumb {
  background: var(--em-accent);
}
.input:focus-visible + .track {
  outline: 2px solid var(--em-accent);
  outline-offset: 3px;
}
.label {
  font-weight: 600;
}
</style>
