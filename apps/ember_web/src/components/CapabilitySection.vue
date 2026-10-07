<script setup lang="ts">
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
    /** The dot before the name; none for a group that is not a real item. */
    status?: "ok" | "bad" | "off";
    dimmed?: boolean;
    page?: SectionPage | null;
    /** A switch, a read-only On/Off badge, or neither. */
    control?: "switch" | "badge" | "none";
    checked?: boolean;
    /** Who the switch is for, shown under it ("Everyone", "You"). */
    scope?: string;
    switchTitle?: string;
    switching?: boolean;
  }>(),
  { status: undefined, page: null, control: "none", scope: "", switchTitle: "" },
);
const emit = defineEmits<{ toggle: []; switch: [] }>();
</script>

<template>
  <article :class="['card', { off: dimmed, open }]">
    <header class="card-head">
      <button type="button" class="head-button" :aria-expanded="open" @click="emit('toggle')">
        <span class="chevron" aria-hidden="true">{{ open ? "▾" : "▸" }}</span>
        <span v-if="status" :class="['dot', status]" aria-hidden="true" />
        <span class="heading">
          <h3>{{ label }}</h3>
          <code class="name">{{ name }}</code>
        </span>
        <span :class="['summary', status === 'bad' ? 'bad' : 'muted']">{{ summary }}</span>
      </button>
      <template v-if="page">
        <span class="divider" aria-hidden="true" />
        <OpenPageButton :to="page.to" :external="page.external" :label="page.label" />
      </template>
      <span v-if="control === 'switch'" class="control">
        <ToggleSwitch
          :title="switchTitle"
          :checked="checked"
          :disabled="switching"
          @click.prevent="emit('switch')"
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
.divider {
  width: 1px;
  height: 20px;
  margin-left: 4px;
  background: var(--border);
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
  color: var(--muted);
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
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 10px;
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
  font-size: 0.85em;
  white-space: nowrap;
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
