<script setup lang="ts">
import { nextTick, ref, watch } from "vue";

/** A destructive action button. While `busy` (the request is in flight) every
 * letter of the label falls into the bin and the button shrinks to a round
 * bin with a spinning ring; when `busy` ends it grows back. The animation only
 * follows `busy`, so it never delays or replaces the action itself. A click
 * while busy is ignored. */
const props = withDefaults(defineProps<{ label?: string; busy?: boolean; disabled?: boolean }>(), {
  label: "Delete",
  busy: false,
  disabled: false,
});
const emit = defineEmits<{ click: [] }>();

const button = ref<HTMLButtonElement | null>(null);
const icon = ref<SVGSVGElement | null>(null);
const letters = ref<HTMLElement[]>([]);
const collapsed = ref(false);

/** Width of the button before it shrank, so it can grow back to exactly that. */
let fullWidth = 0;

function onClick(): void {
  if (props.busy || props.disabled) return;
  emit("click");
}

/** Gives each letter the distance to the bin, so it falls into it from wherever it stands. */
function aimLetters(): void {
  const target = icon.value?.getBoundingClientRect();
  if (!target) return;
  const cx = target.left + target.width / 2;
  const cy = target.top + target.height / 2;
  for (const el of letters.value) {
    const r = el.getBoundingClientRect();
    el.style.setProperty("--dx", `${cx - (r.left + r.width / 2)}px`);
    el.style.setProperty("--dy", `${cy - (r.top + r.height / 2)}px`);
  }
}

async function collapse(): Promise<void> {
  const el = button.value;
  if (!el) return;
  fullWidth = el.offsetWidth;
  el.style.width = `${fullWidth}px`;
  aimLetters();
  await nextTick();
  void el.offsetWidth; // commit the pinned width so the next change transitions
  collapsed.value = true;
  el.style.width = `${el.offsetHeight}px`;
}

function expand(): void {
  const el = button.value;
  if (!el) return;
  collapsed.value = false;
  el.style.width = `${fullWidth}px`;
}

/** Back at full width: let the label size the button again. */
function onTransitionEnd(event: TransitionEvent): void {
  const el = button.value;
  if (event.propertyName === "width" && el && !collapsed.value) el.style.width = "";
}

watch(
  () => props.busy,
  (busy) => void (busy ? collapse() : expand()),
);
</script>

<template>
  <button
    ref="button"
    type="button"
    :class="['delete-button', { collapsed }]"
    :aria-label="label"
    :aria-busy="busy"
    :aria-disabled="disabled || busy"
    :disabled="disabled && !busy"
    @click="onClick"
    @transitionend="onTransitionEnd"
  >
    <svg ref="icon" class="bin" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <g class="lid">
        <path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
      </g>
      <path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M10 11v6M14 11v6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
    <span class="label" aria-hidden="true">
      <span v-for="(ch, i) in label" :key="i" ref="letters" class="letter" :style="{ '--i': i }">{{ ch === " " ? " " : ch }}</span>
    </span>
    <svg class="ring" viewBox="0 0 40 40" aria-hidden="true">
      <circle cx="20" cy="20" r="17" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="26 82" />
    </svg>
  </button>
</template>

<style scoped>
/* button.delete-button, not .delete-button: a parent's `.info-page .danger` (same
 * specificity, loaded later) would otherwise reset the padding the bin needs. */
button.delete-button {
  position: relative;
  box-sizing: border-box;
  height: 34px;
  padding: 0 16px 0 38px;
  overflow: hidden;
  border: 1px solid var(--danger);
  border-radius: var(--radius-full);
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  white-space: nowrap;
  color: var(--danger);
  background: transparent;
  transition: width 0.35s cubic-bezier(0.6, 0, 0.3, 1);
}
button.delete-button:disabled {
  cursor: default;
  opacity: 0.5;
}
.delete-button[aria-busy="true"] {
  cursor: default;
}
.bin {
  position: absolute;
  top: 8px;
  left: 14px;
  transition: left 0.35s cubic-bezier(0.6, 0, 0.3, 1);
}
.lid {
  transform-origin: 20px 7px;
  transition: transform 0.2s ease-out;
}
.letter {
  display: inline-block;
  transition:
    transform 0.2s ease,
    opacity 0.2s ease;
}

/* Busy: the lid opens, the letters drop in one after the other, the button
 * shrinks to the bin and a ring spins round it. */
.collapsed .lid {
  transform: rotate(-24deg) translateY(-1px);
}
.collapsed .letter {
  opacity: 0;
  transform: translate(var(--dx, 0), var(--dy, 0)) scale(0.3);
  transition:
    transform 0.4s cubic-bezier(0.5, 0, 0.9, 0.5) calc(var(--i) * 45ms),
    opacity 0.15s ease-in calc(var(--i) * 45ms + 0.25s);
}
.collapsed .bin {
  left: calc(50% - 8px);
  transition-delay: 0.3s;
}
.ring {
  position: absolute;
  inset: 0;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s ease;
}
.collapsed .ring {
  opacity: 1;
  transition-delay: 0.7s;
  animation: ring-spin 0.9s linear infinite;
}
@keyframes ring-spin {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  button.delete-button,
  .bin,
  .lid,
  .letter,
  .collapsed .letter,
  .collapsed .bin,
  .ring {
    transition: none;
    transition-delay: 0s;
  }
  .collapsed .ring {
    animation-duration: 2.4s;
  }
}
</style>
