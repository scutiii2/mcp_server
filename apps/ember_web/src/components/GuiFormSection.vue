<script setup lang="ts">
import { computed, onActivated, onDeactivated, onScopeDispose, ref } from "vue";
import type { GuiFormSectionSpec } from "../api/CapabilityPagesClient";
import type { ToolInfo, ToolRunResult } from "../api/types";
import { useCountdown } from "../composables/useCountdown";
import { errorMessage } from "../utils/errors";
import { applyFieldOverrides, resultValue } from "../utils/guiPage";
import CountdownRing from "./CountdownRing.vue";
import GuiResult from "./GuiResult.vue";
import ToolRunForm from "./ToolRunForm.vue";

/** One form section of a capability page: the tool's form (built from its own
 * schema), the run, and its result. With `refresh_after` the tool is run again
 * with the same arguments when the countdown ends. With `live` it runs as it
 * opens and again (after a short wait) whenever a control changes. `embedded`
 * (inside tabs) drops the card, title and description and shows the result
 * above the controls. State is memory only. */
const props = defineProps<{
  section: GuiFormSectionSpec;
  tool: ToolInfo;
  runTool: (name: string, args: Record<string, unknown>) => Promise<ToolRunResult>;
  embedded?: boolean;
}>();

/** A burst of changes (several toggles, a typed value) becomes one run. */
const LIVE_DEBOUNCE_MS = 300;

const schema = computed(() => applyFieldOverrides(props.tool.inputSchema, props.section.fields));
const live = computed(() => props.section.live === true);
const running = ref(false);
const result = ref<ToolRunResult | null>(null);
const error = ref("");
// Seconds the current countdown started from, for the ring.
const countdownTotal = ref(0);
let lastArgs: Record<string, unknown> = {};
let ran = false;
let runId = 0;
let disposed = false;
let debounce: ReturnType<typeof setTimeout> | null = null;

function clearDebounce(): void {
  if (debounce !== null) clearTimeout(debounce);
  debounce = null;
}
onScopeDispose(() => {
  disposed = true;
  clearDebounce();
});

const countdown = useCountdown(() => void run(lastArgs));

async function run(args: Record<string, unknown>): Promise<void> {
  lastArgs = args;
  ran = true;
  clearDebounce();
  const id = ++runId;
  running.value = true;
  error.value = "";
  countdown.stop();
  try {
    const res = await props.runTool(props.tool.name, args);
    // A disposed section or an older run must not touch state or restart the countdown.
    if (disposed || id !== runId) return;
    result.value = res;
    const after = props.section.result.refresh_after;
    const seconds = after && !res.isError ? resultValue(res, after) : undefined;
    if (typeof seconds === "number" && seconds > 0) {
      countdownTotal.value = seconds;
      countdown.start(seconds);
    }
  } catch (err) {
    if (disposed || id !== runId) return;
    result.value = null;
    error.value = errorMessage(err);
  } finally {
    if (!disposed && id === runId) running.value = false;
  }
}

/** The form's args: run now (a button press), or, when live, the first time
 * at once and later changes after a short wait. */
function onFormRun(args: Record<string, unknown>): void {
  if (!live.value || !ran) {
    void run(args);
    return;
  }
  lastArgs = args;
  clearDebounce();
  debounce = setTimeout(() => void run(args), LIVE_DEBOUNCE_MS);
}

function again(): void {
  void run(lastArgs);
}

// Inside <KeepAlive> (tabs): a hidden form must not keep calling the tool.
onDeactivated(() => {
  countdown.stop();
  clearDebounce();
});
onActivated(() => {
  if (ran && props.section.result.refresh_after) void run(lastArgs);
});
</script>

<template>
  <section :class="['card', { embedded }]">
    <h3 v-if="!embedded">{{ section.title }}</h3>
    <p v-if="tool.description && !embedded" class="muted">{{ tool.description }}</p>
    <ToolRunForm :schema="schema" :running="running" :submit-label="section.submit" :live="live" @run="onFormRun" />
    <p v-if="error" class="error">{{ error }}</p>
    <GuiResult v-if="result" class="result" :spec="section.result" :result="result" :can-regenerate="live" @again="again" />
    <div v-if="countdown.running.value" class="refresh">
      <CountdownRing :remaining="countdown.remaining.value" :total="countdownTotal" />
      <span class="muted">New code in {{ countdown.remaining.value }} s</span>
    </div>
  </section>
</template>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  margin-bottom: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
}
.card.embedded {
  margin: 0;
  padding: 0;
  border: none;
  background: none;
  gap: 14px;
}
/* Embedded: the result (and its refresh ring) lead, the controls follow. */
.embedded .result,
.embedded .refresh {
  order: -1;
}
.refresh {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.muted {
  color: var(--muted);
}
.error {
  color: var(--danger);
}
</style>
