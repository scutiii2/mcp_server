<script setup lang="ts" generic="T extends string">
// A pill with one segment per choice and a white thumb that slides to the chosen
// one. Plain buttons with aria-pressed, so keyboard and screen readers get a
// button group; segments share the width equally so the thumb can move by whole
// steps. Use it for a handful of mutually exclusive choices.
const props = defineProps<{
  options: readonly { value: T; label: string }[];
  ariaLabel?: string;
}>();

const model = defineModel<T>({ required: true });

/** Position of the chosen option; -1 hides the thumb. */
const index = () => props.options.findIndex((o) => o.value === model.value);
</script>

<template>
  <div class="segmented" role="group" :aria-label="ariaLabel" :style="{ '--n': options.length, '--i': index() }">
    <span :class="['thumb', { hidden: index() < 0 }]" aria-hidden="true" />
    <button
      v-for="o in options"
      :key="o.value"
      type="button"
      :class="{ active: o.value === model }"
      :aria-pressed="o.value === model"
      @click="model = o.value"
    >
      {{ o.label }}
    </button>
  </div>
</template>

<style scoped>
.segmented {
  position: relative;
  display: inline-grid;
  grid-auto-flow: column;
  grid-auto-columns: 1fr;
  max-width: 100%;
  padding: 3px;
  border-radius: var(--radius-full);
  background: var(--accent);
}
.thumb {
  position: absolute;
  top: 3px;
  bottom: 3px;
  left: 3px;
  width: calc((100% - 6px) / var(--n));
  border-radius: var(--radius-full);
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
  transform: translateX(calc(var(--i) * 100%));
  transition: transform 0.18s ease;
}
.thumb.hidden {
  opacity: 0;
}
button {
  position: relative;
  z-index: 1;
  padding: 4px 14px;
  border: none;
  border-radius: var(--radius-full);
  cursor: pointer;
  font-size: 0.85em;
  font-weight: 600;
  white-space: nowrap;
  color: #fff;
  background: transparent;
  transition: color 0.18s ease;
}
button.active {
  color: var(--accent);
}
button:focus-visible {
  outline: 2px solid #fff;
  outline-offset: -2px;
}
</style>
