<script setup lang="ts">
import { CAPABILITY_ICONS } from "../utils/capabilityIcons";
import OpenPageButton from "./OpenPageButton.vue";
import ToggleSwitch from "./ToggleSwitch.vue";

/** Where the section's "Open ..." button leads. */
export interface SectionPage {
  to: string;
  /** A web app in a new tab (up-right arrow) rather than a page of this app. */
  external: boolean;
  label?: string;
}

/** One built-in capability or one extension as a collapsible card: the header
 * (status dot, name, how much it brings, an Open button and an on/off switch)
 * and, when open, whatever the parent puts in the slot. Closed by default; the
 * parent holds the state. The switch only asks (`switch`); the parent decides
 * what flipping it means (a capability for everyone, an extension for you). */
withDefaults(
  defineProps<{
    label: string;
    name: string;
    open: boolean;
    /** The closed summary line: what it brings, or why it brings nothing. */
    summary: string;
    /** The dot on the corner of the icon tile; none for a group that is not a real item. */
    status?: "ok" | "bad" | "off";
    /** The tile's picture: a built-in capability, an extension, or the other tools. */
    icon?: "builtin" | "extension" | "other";
    dimmed?: boolean;
    page?: SectionPage | null;
    /** A switch, a read-only On/Off badge, or neither. */
    control?: "switch" | "badge" | "none";
    checked?: boolean;
    /** Who the switch is for, shown under it ("Everyone", "You"). */
    scope?: string;
    switchTitle?: string;
    switching?: boolean;
    /** The switch is shown but cannot be flipped (the capability is off for everyone). */
    locked?: boolean;
  }>(),
  { status: undefined, icon: undefined, page: null, control: "none", scope: "", switchTitle: "" },
);
const emit = defineEmits<{ toggle: []; switch: [] }>();


</script>

<template>
  <article :class="['card', { off: dimmed, open }]">
    <header class="card-head">
      <button type="button" class="head-button" :aria-expanded="open" @click="emit('toggle')">
        <svg :class="['chevron', { turned: open }]" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <path d="M6 4l4 4-4 4" />
        </svg>
        <span v-if="icon" class="tile" aria-hidden="true">
          <svg viewBox="0 0 16 16" width="18" height="18"><path :d="CAPABILITY_ICONS[icon]" /></svg>
          <span v-if="status" :class="['dot', status]" />
        </span>
        <span v-else-if="status" :class="['dot', 'inline', status]" aria-hidden="true" />
        <span class="heading">
          <h3>{{ label }}</h3>
          <code class="name">{{ name }}</code>
        </span>
        <span :class="['summary', status === 'bad' ? 'bad' : 'muted']">{{ summary }}</span>
      </button>
      <template v-if="page">
        <OpenPageButton :to="page.to" :external="page.external" :label="page.label" />
      </template>
      <span v-if="control === 'switch'" class="control">
        <ToggleSwitch
          :title="switchTitle"
          :checked="checked"
          :disabled="switching || locked"
          @change="emit('switch')"
        />
        <small v-if="scope" class="scope">{{ scope }}</small>
      </span>
      <span v-else-if="control === 'badge'" class="badge">{{ checked ? "On" : "Off" }}</span>
    </header>
    <div v-if="open" class="body">
      <slot />
    </div>
  </article>
</template>

<style scoped>
.card {
  margin-bottom: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.card.off {
  opacity: 0.75;
}
.card.open {
  border-color: var(--accent);
}
.card-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-right: 14px;
}
.head-button {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 12px 0 12px 14px;
  border: none;
  cursor: pointer;
  text-align: left;
  background: transparent;
}
.chevron {
  flex: none;
  fill: none;
  stroke: var(--muted);
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
  transition: transform 0.15s;
}
.chevron.turned {
  transform: rotate(90deg);
}
.tile {
  position: relative;
  display: grid;
  flex: none;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: var(--radius-md);
  background: var(--bg);
}
.tile svg {
  fill: none;
  stroke: var(--accent);
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.tile .dot {
  position: absolute;
  right: -3px;
  bottom: -3px;
  border: 2px solid var(--surface);
  box-sizing: content-box;
}
.dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
}
.dot.ok {
  background: var(--success);
}
.dot.bad {
  background: var(--danger);
}
.dot.off {
  background: var(--muted);
}
.heading {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
h3 {
  margin: 0;
  font-size: 1em;
}
.name {
  font-family: var(--mono);
  font-size: 0.8em;
  color: var(--muted);
  overflow-wrap: anywhere;
}
.summary {
  margin-left: auto;
  padding: 1px 8px;
  border-radius: var(--radius-full);
  font-size: 0.75em;
  white-space: nowrap;
  background: var(--bg);
}
.muted {
  color: var(--muted);
}
.bad {
  color: var(--danger);
}
.control {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 6px 0;
}
.scope {
  font-size: 0.7em;
  color: var(--muted);
}
.badge {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  font-size: 0.75em;
  color: var(--muted);
}
.body {
  display: grid;
  gap: 10px;
  padding: 4px 14px 14px;
  border-top: 1px solid var(--border);
}
</style>
