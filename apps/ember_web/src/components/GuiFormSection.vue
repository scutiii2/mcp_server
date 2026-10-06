<script setup lang="ts">
import { computed, ref } from "vue";
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

const countdown = useCountdown(() => void run(lastArgs));

async function run(args: Record<string, unknown>): Promise<void> {
  lastArgs = args;
  running.value = true;
  error.value = "";
  countdown.stop();
  try {
    result.value = await props.runTool(props.tool.name, args);
    const after = props.section.result.refresh_after;
    const seconds = after && !result.value.isError ? resultValue(result.value, after) : undefined;
    if (typeof seconds === "number" && seconds > 0) countdown.start(seconds);
  } catch (err) {
    result.value = null;
    error.value = errorMessage(err);
  } finally {
    running.value = false;
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
