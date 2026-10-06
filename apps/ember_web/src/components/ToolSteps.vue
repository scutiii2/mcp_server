<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed } from "vue";
import type { ActiveAgent, ToolStep } from "../api/types";
import { stepKey, useChatStore } from "../stores/chat";
import { useEntryAgentStore } from "../stores/entryAgent";
import { formatToolResult } from "../utils/toolResultFormat";
import { toolTitle } from "../utils/toolTitles";
import MarkdownContent from "./MarkdownContent.vue";

/** The tools an answer ran (port of chat_app's "Ran N tools" trace): open
 * while the answer is being written, one collapsed line once it's saved.
 * Each step expands to its arguments and result. */

const props = defineProps<{ steps: ToolStep[]; live?: boolean }>();

const { agentText, activeAgents } = storeToRefs(useChatStore());
const { entry } = storeToRefs(useEntryAgentStore());

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

/** The agent that ran a step, when it was a delegated one (not the main
 * agent). Nothing is badged until the main agent is known. */
function badge(step: ToolStep): string | null {
  const main = entry.value?.id;
  if (!main || !step.agent_id || step.agent_id === main) return null;
  return step.agent_label || step.agent_id;
}

/** The delegated agent working for a delegate step, when it is known: the
 * one right after the step's own agent in the stack (outermost first; the
 * main agent heads it, unlisted). */
function delegateOf(step: ToolStep): ActiveAgent | undefined {
  if (!step.id || !step.agent_id) return undefined;
  const stack = activeAgents.value;
  const at = stack.findIndex((a) => a.agent_id === step.agent_id);
  const next = at >= 0 ? stack[at + 1] : step.agent_id === entry.value?.id ? stack[0] : undefined;
  return next?.step_id === step.id ? next : undefined;
}

/** The key under which a delegate step's text is kept: its working agent's,
 * or (text that came before the agent was announced) any other agent's text
 * for this step id. */
function textKey(step: ToolStep): string | null {
  if (!step.id || !step.agent_id) return null;
  const known = delegateOf(step);
  if (known) return stepKey(known.agent_id, step.id);
  const own = stepKey(step.agent_id, step.id);
  const suffix = stepKey("", step.id);
  return Object.keys(agentText.value).find((k) => k !== own && k.endsWith(suffix)) ?? null;
}

/** A delegated agent's text so far, for the delegate step that handed it its question. */
function workingText(step: ToolStep): string {
  const key = props.live ? textKey(step) : null;
  return key ? (agentText.value[key] ?? "") : "";
}

function workingLabel(step: ToolStep): string {
  return delegateOf(step)?.label || "Delegated agent";
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
        <span v-if="badge(step)" class="agent-badge">{{ badge(step) }}</span>
      </summary>
      <div class="detail">
        <p class="tool"><code>{{ step.tool }}</code></p>
        <pre v-if="argumentsText(step)">{{ argumentsText(step) }}</pre>
        <details v-if="workingText(step)" class="agent-text" open>
          <summary>{{ workingLabel(step) }} is working</summary>
          <pre>{{ workingText(step) }}</pre>
        </details>
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
.agent-badge {
  margin-left: 0.4rem;
  padding: 0 0.4rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--accent);
  font-size: 0.85em;
}
.agent-text {
  margin: 0.3rem 0;
}
.muted {
  margin: 0;
  color: var(--muted);
}
</style>
