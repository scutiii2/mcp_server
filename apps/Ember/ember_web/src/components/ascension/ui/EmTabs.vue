<script setup lang="ts">
import { ref } from "vue";
import EmIcon from "./EmIcon.vue";
import type { IconName } from "./icons";

/** A row of tabs in a dark well: the selected one is raised with a copper rule
 * underneath. Arrow keys, Home and End move between tabs. */
export interface EmTabOption {
  value: string;
  label: string;
  icon?: IconName;
  disabled?: boolean;
}

const props = defineProps<{ modelValue: string; options: EmTabOption[]; ariaLabel: string }>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();
const tabs = ref<HTMLButtonElement[]>([]);

function select(option: EmTabOption): void {
  if (!option.disabled) emit("update:modelValue", option.value);
}

/** Moves the selection by `step` among the enabled tabs; `first` and `last` jump to the ends. */
function move(from: number, step: number | "first" | "last"): void {
  const enabled = props.options.map((o, i) => (o.disabled ? -1 : i)).filter((i) => i >= 0);
  if (enabled.length === 0) return;
  let next: number;
  if (step === "first") next = enabled[0]!;
  else if (step === "last") next = enabled[enabled.length - 1]!;
  else next = enabled[(enabled.indexOf(from) + step + enabled.length) % enabled.length]!;
  emit("update:modelValue", props.options[next]!.value);
  tabs.value[next]?.focus();
}
</script>

<template>
  <div class="em-tabs" role="tablist" :aria-label="ariaLabel">
    <button
      v-for="(option, i) in options"
      :key="option.value"
      ref="tabs"
      type="button"
      role="tab"
      class="tab"
      :class="{ active: option.value === modelValue }"
      :aria-selected="option.value === modelValue"
      :tabindex="option.value === modelValue ? 0 : -1"
      :disabled="option.disabled"
      @click="select(option)"
      @keydown.right.prevent="move(i, 1)"
      @keydown.left.prevent="move(i, -1)"
      @keydown.home.prevent="move(i, 'first')"
      @keydown.end.prevent="move(i, 'last')"
    >
      <EmIcon v-if="option.icon" :name="option.icon" />
      {{ option.label }}
    </button>
  </div>
</template>

<style scoped>
.em-tabs {
  display: inline-flex;
  gap: var(--em-space-1);
  padding: var(--em-space-1);
  border: 1px solid var(--em-border);
  background: var(--em-header);
}
.tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--em-space-2);
  min-height: var(--em-target);
  padding: 10px 18px;
  border: 0;
  border-radius: var(--em-radius);
  color: var(--em-muted);
  background: transparent;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 120ms ease;
}
.tab:hover:not(:disabled) {
  background: #1c2a37;
}
.tab.active {
  color: var(--em-text);
  background: var(--em-raised);
  box-shadow: inset 0 -2px var(--em-accent);
}
.tab:disabled {
  color: var(--em-disabled-text);
  cursor: default;
  opacity: 0.7;
}
@media (max-width: 700px) {
  .em-tabs {
    display: flex;
    width: 100%;
  }
  .tab {
    flex: 1;
    padding: 10px 12px;
    font-size: 12px;
  }
}
</style>
