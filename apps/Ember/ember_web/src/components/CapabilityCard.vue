<script setup lang="ts">
import { ref } from "vue";
import type { ToolInfo } from "../api/types";
import IntegrationToolsModal from "./IntegrationToolsModal.vue";
import OpenPageButton from "./OpenPageButton.vue";
import ToggleSwitch from "./ToggleSwitch.vue";

/** Where the section's "Open ..." button leads. */
export interface SectionPage {
  to: string;
  /** A web app in a new tab (up-right arrow) rather than a page of this app. */
  external: boolean;
  label?: string;
}

/** Compact account card that opens its integration workspace. */
const props = withDefaults(
  defineProps<{
    label: string;
    name: string;
    tools?: ToolInfo[];
    names?: string[];
    /** What this integration brings, or why it is unavailable. */
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
const emit = defineEmits<{ switch: [] }>();
const opened = ref(false);


</script>

<template>
  <article :class="['card', { off: dimmed }]">
    <header class="card-head">
      <button type="button" class="head-button" aria-haspopup="dialog" :aria-expanded="opened" @click="opened = true">
        <span class="heading"><h3>{{ label }}</h3><span class="identity-line"><code class="name">{{ name }}</code><span v-if="status" class="state" :class="status"><span aria-hidden="true">{{ status === 'ok' ? '●' : '○' }}</span> {{ status === 'ok' ? (icon === 'extension' ? 'Connected' : 'Online') : status === 'bad' ? 'Not connected' : 'Offline' }}</span></span><span class="summary">{{ summary }}</span></span>
      </button>
      <span v-if="control === 'switch'" class="control"><ToggleSwitch :title="switchTitle" :checked="checked" :disabled="switching || locked" @change="emit('switch')" /><small v-if="scope" class="scope">{{ scope }}</small></span>
      <span v-else-if="control === 'badge'" class="badge">{{ checked ? 'On' : 'Off' }}</span>
    </header>
    <div v-if="page" class="page-link"><OpenPageButton :to="page.to" :external="page.external" :label="page.label" /></div>
  </article>
  <IntegrationToolsModal v-if="opened" :open="opened" :title="label" :identity="name" :names="names ?? (tools ?? []).map(t => t.name)" :provided-tools="tools ?? []" :available="!dimmed && status !== 'bad' && status !== 'off'" :kind="icon === 'extension' ? 'extension' : 'capability'" :private-extension="scope === 'Private'" @close="opened = false">
    <template #description><slot name="description"><p>{{ scope === 'Private' ? 'Tools for your private conversations.' : `Explore the tools provided by ${props.label}.` }}</p></slot></template>
    <slot />
    <template #reader><slot name="reader" /></template>
  </IntegrationToolsModal>
</template>
<style scoped>
.card { position: relative; padding: 14px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface); transition: border-color .15s ease; }
.card:hover { border-color: var(--accent); }
.card.off { opacity: .75; }
.card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.head-button { border: none; padding: 0; background: transparent; color: inherit; text-align: left; cursor: pointer; font: inherit; min-width: 0; }
.head-button::after { content: ''; position: absolute; inset: 0; border-radius: var(--radius-lg); }
.head-button:focus-visible { outline: none; }
.head-button:focus-visible::after { box-shadow: inset 0 0 0 2px var(--accent); }
.heading { display: grid; gap: 6px; }
h3 { margin: 0; font-size: 1em; font-weight: 600; }
.identity-line { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.name { font: .8em var(--mono); color: var(--muted); overflow-wrap: anywhere; }
.state { font-size: .8em; color: var(--muted); }
.state.ok { color: var(--success); }
.state.bad { color: var(--danger); }
.summary { font-size: .9em; color: var(--muted); display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; }
.control, .page-link { position: relative; z-index: 1; }
.control { display: grid; justify-items: center; flex-shrink: 0; gap: 2px; }
.scope { font-size: .7em; color: var(--muted); }
.page-link { margin-top: 10px; width: fit-content; }
@media (prefers-reduced-motion: reduce) { .card { transition: none; } }
</style>
