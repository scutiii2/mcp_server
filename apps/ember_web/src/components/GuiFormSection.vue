<script setup lang="ts">
import { computed, onScopeDispose, ref } from "vue";
import type { GuiFormSectionSpec } from "../api/CapabilityPagesClient";
import type { ToolInfo, ToolRunResult } from "../api/types";
import { useCountdown } from "../composables/useCountdown";
import { errorMessage } from "../utils/errors";
import { applyFieldOverrides, resultValue } from "../utils/guiPage";
import GuiResult from "./GuiResult.vue";
import ToolRunForm from "./ToolRunForm.vue";

/** One form section of a capability page: the tool's form (built from its own
 * schema), the run, and its result. With `refresh_after` the tool is run again
 * with the same arguments when the countdown ends. State is memory only. */
const props = defineProps<{
  section: GuiFormSectionSpec;
  tool: ToolInfo;
  runTool: (name: string, args: Record<string, unknown>) => Promise<ToolRunResult>;
}>();

const schema = computed(() => applyFieldOverrides(props.tool.inputSchema, props.section.fields));
const running = ref(false);
const result = ref<ToolRunResult | null>(null);
const error = ref("");
let lastArgs: Record<string, unknown> = {};
let runId = 0;
let disposed = false;
onScopeDispose(() => {
  disposed = true;
});

const countdown = useCountdown(() => void run(lastArgs));

async function run(args: Record<string, unknown>): Promise<void> {
  lastArgs = args;
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
    if (typeof seconds === "number" && seconds > 0) countdown.start(seconds);
  } catch (err) {
    if (disposed || id !== runId) return;
    result.value = null;
    error.value = errorMessage(err);
  } finally {
    if (!disposed && id === runId) running.value = false;
  }
}
</script>

<template>
  <section class="card">
    <h3>{{ section.title }}</h3>
    <p v-if="tool.description" class="muted">{{ tool.description }}</p>
    <ToolRunForm :schema="schema" :running="running" :submit-label="section.submit" @run="run" />
    <p v-if="error" class="error">{{ error }}</p>
    <GuiResult v-if="result" :spec="section.result" :result="result" />
    <p v-if="countdown.running.value" class="muted">New code in {{ countdown.remaining.value }} s</p>
  </section>
</template>

<style scoped>
.card {
  margin-bottom: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
}
.muted {
  color: var(--muted);
}
.error {
  color: var(--danger);
}
</style>
