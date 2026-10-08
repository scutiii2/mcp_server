<script setup lang="ts" generic="T extends string">
import { onBeforeUnmount, onMounted, ref, watchPostEffect } from "vue";

// A neutral button group with an accent highlight that slides between choices.
// Measure the selected button so labels can have different widths.
const props = defineProps<{
  options: readonly { value: T; label: string }[];
  ariaLabel?: string;
  label?: string;
}>();

const model = defineModel<T>({ required: true });
const root = ref<HTMLDivElement>();
const buttons = ref<HTMLButtonElement[]>([]);
const position = ref({ left: 0, top: 0, width: 0, height: 0 });
let observer: ResizeObserver | undefined;

function updatePosition(): void {
  const selected = buttons.value.find((button) => button.dataset.value === model.value);
  position.value = selected
    ? { left: selected.offsetLeft, top: selected.offsetTop, width: selected.offsetWidth, height: selected.offsetHeight }
    : { left: 0, top: 0, width: 0, height: 0 };
}

watchPostEffect(() => {
  // Options and model can change without a click (URL navigation, permissions).
  void props.options;
  updatePosition();
  observer?.disconnect();
  if (root.value) observer?.observe(root.value);
  buttons.value.forEach((button) => observer?.observe(button));
});
onMounted(() => {
  if (typeof ResizeObserver !== "undefined") {
    observer = new ResizeObserver(updatePosition);
    if (root.value) observer.observe(root.value);
    buttons.value.forEach((button) => observer?.observe(button));
  }
  updatePosition();
});
onBeforeUnmount(() => observer?.disconnect());
</script>

<template>
  <div class="segmented-control" role="group" :aria-label="ariaLabel ?? label">
    <span v-if="label" class="group-label">{{ label }}</span>
    <div ref="root" class="segmented">
    <span class="thumb" aria-hidden="true" :style="{ width: `${position.width}px`, height: `${position.height}px`, top: `${position.top}px`, transform: `translateX(${position.left}px)`, opacity: position.width ? 1 : 0 }" />
    <button
      v-for="o in options"
      :key="o.value"
      ref="buttons"
      :data-value="o.value"
      type="button"
      class="segment"
      :class="{ active: o.value === model }"
      :aria-pressed="o.value === model"
      @click="model = o.value"
    >
      {{ o.label }}
    </button>
    </div>
  </div>
</template>

<style scoped>
.segmented-control { display: inline-flex; flex-direction: column; gap: 7px; min-width: 0; max-width: 100%; }
.group-label { padding-left: 8px; font-size: 0.8em; font-weight: 500; color: var(--muted); }
.segmented {
  position: relative;
  display: inline-flex;
  gap: 4px;
  max-width: 100%;
  overflow-x: auto;
  padding: 4px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  background: var(--surface);
  align-self: flex-start;
}
.thumb {
  position: absolute;
  top: 0;
  left: 0;
  border-radius: var(--radius-full);
  background: color-mix(in srgb, var(--accent) 10%, var(--bg));
  pointer-events: none;
  transition: transform 0.18s ease, width 0.18s ease;
}
button.segment {
  position: relative;
  z-index: 1;
  flex: 0 0 auto;
  padding: 7px 16px;
  border: none;
  border-radius: var(--radius-full);
  cursor: pointer;
  font-size: 0.85em;
  font-weight: 400;
  white-space: nowrap;
  color: var(--muted);
  background: transparent;
  transition: color 0.18s ease;
}
button.segment.active {
  color: var(--accent);
  font-weight: 600;
}
button.segment:hover {
  color: var(--accent);
}
button.segment:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
@media (max-width: 767px) { button.segment { padding: 7px 10px; } }
@media (prefers-reduced-motion: reduce) { .thumb, button.segment { transition: none; } }
</style>
