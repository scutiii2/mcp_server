<script setup lang="ts">
// A pill on/off switch: a real checkbox (keyboard, focus, disabled and the
// parent's :checked / @change / @click all behave as on a plain input) drawn as
// a sliding knob. `small` drops the ON/OFF text for tight spots such as menus.
// The default slot is the label text beside the pill.
defineOptions({ inheritAttrs: false });

defineProps<{ small?: boolean; title?: string }>();
</script>

<template>
  <label :class="['toggle', { small }]" :title="title">
    <input v-bind="$attrs" type="checkbox" role="switch" class="input" />
    <span class="track" aria-hidden="true">
      <span v-if="!small" class="state">
        <span class="on">ON</span>
        <span class="off">OFF</span>
      </span>
      <span class="knob" />
    </span>
    <span v-if="$slots.default" class="text"><slot /></span>
  </label>
</template>

<style scoped>
.toggle {
  --w: 52px;
  --h: 24px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.toggle.small {
  --w: 32px;
  --h: 18px;
}
.toggle:has(.input:disabled) {
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
  width: var(--w);
  height: var(--h);
  border-radius: 999px;
  background: color-mix(in srgb, var(--muted) 35%, var(--surface));
  transition: background 0.15s ease;
}
.knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: calc(var(--h) - 6px);
  height: calc(var(--h) - 6px);
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
  transition: transform 0.15s ease;
}
.state {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  font-size: 0.62em;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: #fff;
}
.on,
.off {
  position: absolute;
  width: calc(var(--w) - var(--h));
  text-align: center;
}
.on {
  left: 0;
  display: none;
}
.off {
  right: 0;
  color: var(--text);
  opacity: 0.7;
}
.input:checked + .track {
  background: var(--accent);
}
.input:checked + .track .knob {
  transform: translateX(calc(var(--w) - var(--h)));
}
.input:checked + .track .on {
  display: block;
}
.input:checked + .track .off {
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
