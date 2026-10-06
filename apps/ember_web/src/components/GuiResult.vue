<script setup lang="ts">
import { computed, ref } from "vue";
import type { GuiResultSpec } from "../api/CapabilityPagesClient";
import type { ToolRunResult } from "../api/types";
import { resultValue } from "../utils/guiPage";
import { groupText, segmentsOf, strengthOf } from "../utils/secretDisplay";

/** One tool result drawn the way its page asked: a copyable secret, a message,
 * a table or a label/value list. Values stay in this component's memory. */
const props = defineProps<{ spec: GuiResultSpec; result: ToolRunResult; canRegenerate?: boolean; running?: boolean }>();
const emit = defineEmits<{ again: [] }>();

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

// What the person reads: spaced when the page asks for groups. Copy uses secretText.
const shown = computed(() => (props.spec.group ? groupText(secretText.value, props.spec.group) : secretText.value));
const segments = computed(() => segmentsOf(shown.value));
const hiddenText = computed(() => "•".repeat(Math.min(secretText.value.length, 32)));
const strength = computed(() => {
  const bits = props.spec.strength ? resultValue(props.result, props.spec.strength) : undefined;
  return typeof bits === "number" ? { bits, ...strengthOf(bits) } : null;
});

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
      <div v-else class="secret-card">
        <div class="secret-row">
          <code data-test="secret" class="secret"><template v-if="revealed"><span v-for="(s, i) in segments" :key="i" :class="s.kind">{{ s.text }}</span></template><template v-else>{{ hiddenText }}</template></code>
          <button type="button" class="icon" data-test="toggle" :aria-label="revealed ? 'Hide' : 'Show'" :title="revealed ? 'Hide' : 'Show'" @click="revealed = !revealed">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
              <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.8" />
              <path v-if="!revealed" d="M4 4l16 16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
            </svg>
          </button>
          <button v-if="canRegenerate" type="button" class="icon" data-test="again" aria-label="Generate again" title="Generate again" :disabled="running" @click="emit('again')">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M20 12a8 8 0 1 1-2.6-5.9M20 4v5h-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
          <button type="button" class="copy" data-test="copy" @click="copy">{{ copied ? "Copied" : "Copy" }}</button>
        </div>
        <div v-if="strength" class="strength">
          <div class="bar" aria-hidden="true"><div :class="['fill', strength.level]" :style="{ width: `${strength.fraction * 100}%` }" /></div>
          <div class="strength-meta">
            <span data-test="strength">{{ strength.label }}</span>
            <span data-test="bits">{{ Math.round(strength.bits) }} bits of entropy</span>
          </div>
        </div>
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
.secret-card { display: flex; flex-direction: column; gap: 12px; padding: 14px 16px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg); }
.secret-row { display: flex; gap: 8px; align-items: center; }
.secret { flex: 1; min-width: 0; font-family: var(--mono); font-size: 1.25em; line-height: 1.5; word-break: break-all; }
.digit { color: var(--accent); }
.symbol { color: var(--success); }
.icon, .copy { display: inline-flex; align-items: center; justify-content: center; height: 34px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); color: var(--text); cursor: pointer; }
.icon { width: 34px; padding: 0; }
.icon:disabled { cursor: default; opacity: 0.5; }
.copy { padding: 0 14px; font-weight: 600; }
.bar { height: 6px; border-radius: var(--radius-full); background: var(--surface); overflow: hidden; }
.fill { height: 100%; border-radius: var(--radius-full); transition: width 0.25s, background-color 0.25s; }
.fill.weak { background: var(--danger); }
.fill.fair { background: var(--warning); }
.fill.strong, .fill.excellent { background: var(--success); }
.strength-meta { display: flex; justify-content: space-between; margin-top: 6px; font-size: 0.8em; color: var(--muted); }
@media (prefers-reduced-motion: reduce) { .fill { transition: none; } }
.error { color: var(--danger); }
.fields { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; }
table { border-collapse: collapse; }
th, td { padding: 4px 10px; border-bottom: 1px solid var(--border); text-align: left; }
</style>
