<script setup lang="ts">
import { computed, ref } from "vue";
import type { ChatMessage } from "../api/types";
import { formatDuration, usageSummary } from "../utils/usageFormat";

const props = defineProps<{ message: ChatMessage }>();

const open = ref(false);
const summary = computed(() => usageSummary(props.message));

interface Row {
  label: string;
  value: string;
}

/** What the detail panel lists; a row appears only when its value was saved. */
const rows = computed<Row[]>(() => {
  const m = props.message;
  const list: Row[] = [];
  if (m.model) list.push({ label: "Model", value: m.model });
  if (m.input_tokens !== undefined) list.push({ label: "Input tokens", value: m.input_tokens.toLocaleString() });
  if (m.output_tokens !== undefined) list.push({ label: "Output tokens", value: m.output_tokens.toLocaleString() });
  if (m.total_tokens !== undefined) list.push({ label: "Total tokens", value: m.total_tokens.toLocaleString() });
  if (m.duration_s !== undefined) list.push({ label: "Time", value: formatDuration(m.duration_s) });
  if (m.steps?.length) {
    const failed = m.steps.filter((s) => s.ok === false).length;
    list.push({ label: "Tools run", value: failed ? `${m.steps.length} (${failed} failed)` : String(m.steps.length) });
  }
  if (m.context_tokens && m.context_window) {
    const percent = Math.min(100, Math.round((m.context_tokens / m.context_window) * 100));
    list.push({
      label: "Context",
      value: `${m.context_tokens.toLocaleString()} of ${m.context_window.toLocaleString()} (${percent}%)`,
    });
  }
  return list;
});
</script>

<template>
  <!-- display: contents: the button sits in the parent's action row and the
       panel wraps onto its own line below it. -->
  <div v-if="summary" class="usage">
    <button
      type="button"
      class="chip"
      :aria-expanded="open"
      title="Usage details"
      @click="open = !open"
      @keydown.esc="open = false"
    >
      {{ summary }}
    </button>
    <dl v-if="open" class="panel" @keydown.esc="open = false">
      <template v-for="r in rows" :key="r.label">
        <dt>{{ r.label }}</dt>
        <dd>{{ r.value }}</dd>
      </template>
    </dl>
  </div>
</template>

<style scoped>
.usage {
  display: contents;
}
.chip {
  padding: 2px 6px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font: inherit;
  font-size: 0.75em;
  color: var(--muted);
  background: transparent;
}
.chip:hover,
.chip[aria-expanded="true"] {
  color: var(--text);
  background: var(--surface);
}
.panel {
  flex: 1 0 100%;
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 2px 16px;
  margin: 2px 0 0;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 0.8em;
  background: var(--surface);
}
.panel dt {
  color: var(--muted);
}
.panel dd {
  margin: 0;
  overflow-wrap: anywhere;
}
</style>
