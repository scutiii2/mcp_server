<script setup lang="ts">
import { computed } from "vue";
import type { ToolStep } from "../api/types";
import { formatToolResult } from "../utils/toolResultFormat";
import { toolTitle } from "../utils/toolTitles";
import MarkdownContent from "./MarkdownContent.vue";

/** The tools an answer ran (port of chat_app's "Ran N tools" trace): open
 * while the answer is being written, one collapsed line once it's saved.
 * Each step expands to its arguments and result. */

const props = defineProps<{ steps: ToolStep[]; live?: boolean }>();

const failed = computed(() => props.steps.filter((s) => s.ok === false).length);
const summary = computed(() => {
  if (props.live) return "Running tools ...";
  const n = props.steps.length;
  return `Ran ${n} tool${n === 1 ? "" : "s"}${failed.value ? ` (${failed.value} failed)` : ""}`;
});

function icon(step: ToolStep): string {
  if (step.ok === null) return props.live ? "⏳" : "⚠️";
  return step.ok ? "✓" : "✗";
}

function title(step: ToolStep): string {
  return step.label || toolTitle(step.tool);
}

function argumentsText(step: ToolStep): string {
  return Object.keys(step.arguments).length ? JSON.stringify(step.arguments, null, 2) : "";
}
</script>

<template>
  <details class="steps" :open="live">
    <summary>{{ summary }}</summary>
    <details v-for="(step, i) in steps" :key="i" :class="['step', { failed: step.ok === false }]">
      <summary>
        <span class="icon">{{ icon(step) }}</span>
        <span class="title">{{ title(step) }}</span>
      </summary>
      <div class="detail">
        <p class="tool"><code>{{ step.tool }}</code></p>
        <pre v-if="argumentsText(step)">{{ argumentsText(step) }}</pre>
        <template v-if="step.result">
          <MarkdownContent v-if="formatToolResult(step.result)" :text="formatToolResult(step.result) ?? ''" />
          <pre v-else>{{ step.result }}</pre>
        </template>
        <p v-else-if="step.ok === null" class="muted">{{ live ? "running ..." : "no result (the answer was stopped)" }}</p>
      </div>
    </details>
  </details>
</template>

<style scoped>
.steps {
  font-size: 0.85em;
  color: var(--muted);
}
.steps > summary {
  cursor: pointer;
}
.step {
  margin: 4px 0 0 14px;
}
.step > summary {
  cursor: pointer;
}
.icon {
  display: inline-block;
  width: 1.4em;
}
.failed .icon {
  color: #d4513b;
}
.title {
  color: var(--text);
}
.detail {
  margin: 4px 0 8px 1.4em;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  overflow-wrap: anywhere;
}
.tool {
  margin: 0 0 6px;
}
.detail pre {
  max-height: 280px;
  margin: 0 0 6px;
  padding: 8px;
  overflow: auto;
  border-radius: 6px;
  white-space: pre-wrap;
  font-family: var(--mono);
  background: var(--code-bg);
}
.muted {
  margin: 0;
  color: var(--muted);
}
</style>
