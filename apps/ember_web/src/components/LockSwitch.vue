<script setup lang="ts">
// A lock-style on/off switch for security-flavoured settings: an outlined track
// with a square knob and a padlock on the other side (open when off, closed when
// on). Same contract as ToggleSwitch: a real checkbox, so the parent's :checked /
// :disabled / @change / @click behave as on a plain input. The default slot is
// the label text beside the switch.
defineOptions({ inheritAttrs: false });

defineProps<{ title?: string }>();
</script>

<template>
  <label class="lock" :title="title">
    <input v-bind="$attrs" type="checkbox" role="switch" class="input" />
    <span class="track" aria-hidden="true">
      <span class="knob" />
      <svg class="icon" viewBox="0 0 24 24" width="18" height="18">
        <rect x="5" y="11" width="14" height="9" rx="2.5" />
        <path class="shackle-closed" d="M8 11V8a4 4 0 0 1 8 0v3" />
        <path class="shackle-open" d="M8 11V8a4 4 0 0 1 7.5-2" />
        <circle cx="12" cy="15.5" r="0.6" />
      </svg>
    </span>
    <span v-if="$slots.default" class="text"><slot /></span>
  </label>
</template>

<style scoped>
.lock {
  --w: 62px;
  --h: 30px;
  --tone: color-mix(in srgb, var(--muted) 45%, var(--surface));
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.lock:has(.input:disabled) {
  cursor: default;
  opacity: 0.6;
}
.input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}
.track {
  position: relative;
  flex: none;
  box-sizing: border-box;
  width: var(--w);
  height: var(--h);
  border: 2px solid var(--tone);
  border-radius: var(--radius-md);
  color: var(--tone);
  transition: border-color 0.15s ease, color 0.15s ease;
}
.knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: calc(var(--h) - 10px);
  height: calc(var(--h) - 10px);
  border-radius: calc(var(--radius-md) - 5px);
  background: var(--tone);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
  transition: transform 0.15s ease, background 0.15s ease;
}
.icon {
  position: absolute;
  top: 50%;
  right: 6px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
  transform: translateY(-50%);
}
.icon circle {
  fill: currentColor;
}
.shackle-closed {
  display: none;
}
.input:checked + .track {
  border-color: var(--accent);
  color: var(--accent);
}
.input:checked + .track .knob {
  background: var(--accent);
  transform: translateX(calc(var(--w) - var(--h)));
}
.input:checked + .track .icon {
  right: auto;
  left: 6px;
}
.input:checked + .track .shackle-closed {
  display: block;
}
.input:checked + .track .shackle-open {
  display: none;
}
.input:focus-visible + .track {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.text {
  font-size: 0.9em;
}
</style>
