<script setup lang="ts">
import type { CapabilityInfo } from "../api/CommandsClient";

/** One built-in capability as a collapsible card: the header (name, how much
 * it brings, and for admins the on/off switch) and, when open, whatever the
 * parent puts in the slot. Closed by default; the parent holds the state. */
defineProps<{
  capability: CapabilityInfo;
  open: boolean;
  /** Tools and resources it brings, for the closed summary line. */
  toolCount: number;
  resourceCount: number;
  isAdmin: boolean;
  switching: boolean;
  /** No on/off state to show (a group that is not a real capability). */
  hideState?: boolean;
}>();
const emit = defineEmits<{ toggle: []; switch: [] }>();
</script>

<template>
  <article :class="['card', { off: !capability.enabled, open }]">
    <header class="card-head">
      <button type="button" class="head-button" :aria-expanded="open" @click="emit('toggle')">
        <span class="chevron" aria-hidden="true">{{ open ? "▾" : "▸" }}</span>
        <span class="heading">
          <h3>{{ capability.label ?? capability.name }}</h3>
          <code class="name">{{ capability.name }}</code>
        </span>
        <span class="summary muted">
          <template v-if="!capability.enabled">off</template>
          <template v-else>
            {{ toolCount }} tool{{ toolCount === 1 ? "" : "s" }}<template v-if="resourceCount">
              · {{ resourceCount }} resource{{ resourceCount === 1 ? "" : "s" }}</template
            >
          </template>
        </span>
      </button>
      <template v-if="hideState" />
      <label v-else-if="isAdmin" class="switch" :title="capability.enabled ? 'Turn off' : 'Turn on'">
        <input type="checkbox" :checked="capability.enabled" :disabled="switching" @click.prevent="emit('switch')" />
        {{ capability.enabled ? "On" : "Off" }}
      </label>
      <span v-else class="badge">{{ capability.enabled ? "On" : "Off" }}</span>
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
  border-radius: 10px;
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
  color: var(--muted);
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
.switch {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.85em;
  cursor: pointer;
}
.badge {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
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
