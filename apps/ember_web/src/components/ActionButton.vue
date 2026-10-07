<script setup lang="ts">
/** An outlined action button with an icon, shared by the chat toolbar and the
 * Usage page. The icon takes the accent colour; `quiet` mutes it for the
 * secondary maintenance actions. Below 480px only the icon stays; the label
 * remains for screen readers. */
export type ActionIcon = "export" | "share" | "summarize" | "clear";

// 16px viewBox, stroke only, drawn like the arrows in OpenPageButton.
const PATHS: Record<ActionIcon, string> = {
  export: "M8 2v8M5 7l3 3 3-3M3 13h10",
  share: "M8 10V2M5 5l3-3 3 3M3 9v4h10V9",
  summarize: "M3 4h10M3 8h7M3 12h5",
  clear: "M3 5h10M6 5V3h4v2M5 5l.5 8h5L11 5",
};

defineProps<{ icon: ActionIcon; quiet?: boolean }>();
</script>

<template>
  <button type="button" :class="['action', { quiet }]">
    <svg class="icon" viewBox="0 0 16 16" aria-hidden="true"><path :d="PATHS[icon]" /></svg>
    <span class="label"><slot /></span>
  </button>
</template>

<style scoped>
.action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  cursor: pointer;
  background: var(--bg);
  color: var(--text);
  font-size: 0.85rem;
  line-height: 1.4;
  white-space: nowrap;
}
.action.quiet {
  color: var(--muted);
}
.action:hover:not(:disabled) {
  border-color: var(--accent);
}
.action:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.action:disabled {
  cursor: default;
  opacity: 0.5;
}
.icon {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: var(--accent);
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.quiet .icon {
  stroke: currentColor;
}
@media (max-width: 480px) {
  .label {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
  .action {
    padding: 6px;
  }
}
</style>
