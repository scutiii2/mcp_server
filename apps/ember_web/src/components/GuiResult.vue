<script setup lang="ts">
import { computed, ref } from "vue";
import type { GuiResultSpec } from "../api/CapabilityPagesClient";
import type { ToolRunResult } from "../api/types";
import { resultValue } from "../utils/guiPage";

/** One tool result drawn the way its page asked: a copyable secret, a message,
 * a table or a label/value list. Values stay in this component's memory. */
const props = defineProps<{ spec: GuiResultSpec; result: ToolRunResult }>();

const value = computed(() => (props.spec.field ? resultValue(props.result, props.spec.field) : undefined));
const detail = computed(() => {
  const v = props.spec.detail ? resultValue(props.result, props.spec.detail) : undefined;
  return typeof v === "string" ? v : "";
});
const message = computed(() => {
  const v = resultValue(props.result, props.spec.field ?? "message");
  return typeof v === "string" ? v : props.result.text;
});

const revealed = ref(true);
const copied = ref(false);
const secretText = computed(() => (value.value === undefined || value.value === null ? "" : String(value.value)));

async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(secretText.value);
    copied.value = true;
    setTimeout(() => (copied.value = false), 1500);
  } catch {
    // Clipboard blocked (permissions / insecure context): nothing to do.
  }
}

const rows = computed<Record<string, unknown>[]>(() =>
  Array.isArray(value.value) ? (value.value as unknown[]).filter((r): r is Record<string, unknown> => typeof r === "object" && r !== null) : [],
);
const columns = computed(() => [...new Set(rows.value.flatMap((r) => Object.keys(r)))]);

const scalars = computed(() =>
  Object.entries(props.result.structured ?? {}).filter(([, v]) => ["string", "number", "boolean"].includes(typeof v)),
);
</script>

<template>
  <div :class="['gui-result', { failed: result.isError }]">
    <p v-if="result.isError" class="error">{{ result.text || "The tool reported an error." }}</p>
    <template v-else-if="spec.kind === 'secret'">
      <p v-if="secretText === ''" class="muted">The tool returned no value for '{{ spec.field }}'.</p>
      <div v-else class="secret-row">
        <code data-test="secret" class="secret">{{ revealed ? secretText : "•".repeat(Math.min(secretText.length, 32)) }}</code>
        <button type="button" data-test="toggle" @click="revealed = !revealed">{{ revealed ? "Hide" : "Show" }}</button>
        <button type="button" data-test="copy" @click="copy">{{ copied ? "Copied" : "Copy" }}</button>
      </div>
      <p v-if="detail" class="muted">{{ detail }}</p>
    </template>
    <p v-else-if="spec.kind === 'message'">{{ message }}</p>
    <template v-else-if="spec.kind === 'table'">
      <p v-if="rows.length === 0" class="muted">No rows.</p>
      <table v-else>
        <thead><tr><th v-for="c in columns" :key="c">{{ c }}</th></tr></thead>
        <tbody><tr v-for="(r, i) in rows" :key="i"><td v-for="c in columns" :key="c">{{ r[c] ?? "" }}</td></tr></tbody>
      </table>
    </template>
    <dl v-else class="fields">
      <template v-for="[k, v] in scalars" :key="k"><dt>{{ k }}</dt><dd>{{ v }}</dd></template>
    </dl>
  </div>
</template>

<style scoped>
.gui-result { margin-top: 12px; }
.secret-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.secret { padding: 6px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); word-break: break-all; }
.error { color: var(--danger); }
.fields { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; }
table { border-collapse: collapse; }
th, td { padding: 4px 10px; border-bottom: 1px solid var(--border); text-align: left; }
</style>
