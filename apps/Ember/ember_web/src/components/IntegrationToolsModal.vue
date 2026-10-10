<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { commandsClient } from "../api/CommandsClient";
import { McpServerClient } from "../api/McpServerClient";
import type { ToolInfo, ToolRunResult } from "../api/types";
import { useAuthStore } from "../stores/auth";
import { errorMessage } from "../utils/errors";
import { commandsByTool } from "../utils/toolCommands";
import BaseModal from "./BaseModal.vue";
import CopyButton from "./CopyButton.vue";
import ToolResultPanel from "./ToolResultPanel.vue";
import ToolRunForm from "./ToolRunForm.vue";


const props = defineProps<{ open: boolean; title: string; identity: string; names: string[]; available: boolean; kind?: "capability" | "extension"; status?: string; providedTools: ToolInfo[]; privateExtension?: boolean }>();
const emit = defineEmits<{ close: [] }>();
const auth = useAuthStore();
const client = new McpServerClient();
const tools = computed(() => canBrowse.value && props.available ? props.providedTools : []);
const search = ref("");
const registry = ref<Awaited<ReturnType<typeof commandsClient.list>>>([]);
const commands = computed(() => {
  if (!props.available) return new Map<string, string>();
  return commandsByTool(registry.value, props.names, props.kind === "extension" && !props.privateExtension ? props.identity : null);
});
let commandsLoaded = false;
/** The command registry is read once; without it the modal just shows no commands. */
async function loadCommands(): Promise<void> {
  if (commandsLoaded) return;
  commandsLoaded = true;
  try { registry.value = await commandsClient.list(); } catch { commandsLoaded = false; }
}
watch(() => props.open, (open) => { if (open) void loadCommands(); }, { immediate: true });
const visibleTools = computed(() => {
  const query = search.value.trim().toLowerCase();
  return props.names.map((name) => ({ name, tool: tools.value.find((tool) => tool.name === name) }))
    .filter(({ name, tool }) => `${name} ${tool?.title ?? ""} ${tool?.description ?? ""}`.toLowerCase().includes(query));
});
const selected = ref<ToolInfo | null>(null);
const running = ref(false);
const result = ref<ToolRunResult | null>(null);
const canBrowse = computed(() => auth.hasPermission("tools.view") || auth.hasPermission("tools.execute"));
const canRun = computed(() => auth.hasPermission("tools.execute") && props.available && !props.privateExtension);
let generation = 0;
watch(() => [props.open, props.identity, props.available, props.names.join("\n"), props.providedTools, canBrowse.value], () => {
  ++generation;
  search.value = "";
  selected.value = null;
  result.value = null;
}, { immediate: true });
function choose(tool: ToolInfo): void {
  if (running.value) return;
  selected.value = tool;
  result.value = null;
}
async function run(args: Record<string, unknown>): Promise<void> {
  const tool = selected.value;
  if (!tool || running.value || !canRun.value) return;
  const request = generation;
  running.value = true;
  result.value = null;
  try {
    const outcome = await client.runTool(tool.name, args);
    if (request === generation) result.value = outcome;
  } catch (err) {
    if (request === generation) result.value = { text: errorMessage(err), isError: true };
  } finally { running.value = false; }
}
function close(): void { if (!running.value) emit("close"); }
</script>

<template>
  <BaseModal :open="open" :title="title" class="integration-modal" @close="close">
    <div class="tools-modal">
      <div class="integration-summary">
        <span class="integration-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path v-if="kind === 'extension'" d="M12 2v6M8 8h8v4a4 4 0 0 1-8 0zM12 16v6" /><path v-else d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5" /></svg></span>
        <div class="summary-copy"><div class="metadata"><span class="kind">{{ privateExtension ? 'Private extension' : kind === 'extension' ? 'Shared extension' : 'Capability' }}</span><code class="identity">{{ identity }}</code></div><div class="summary-description"><slot name="description"><p>Explore the tools provided by {{ title }}.</p></slot></div></div>
        <span class="availability" :class="{ online: available }"><span aria-hidden="true">{{ available ? '●' : '○' }}</span> {{ status ?? (available ? 'Available' : 'Unavailable') }}</span>
      </div>
      <div class="workspace">
        <section class="tool-browser" aria-label="Tool browser">
          <div class="section-heading"><h4>Tools</h4><span class="tool-count">{{ names.length }}</span></div>
          <label class="tool-search"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0" /></svg><input v-model="search" type="search" placeholder="Find a tool" aria-label="Find a tool" :disabled="running" /></label>
          <p v-if="!names.length" class="browser-note">No tools are available.</p>
          <ul v-else class="tool-list" :aria-busy="running">
            <li v-for="{ name, tool } in visibleTools" :key="name">
              <button type="button" :disabled="running || !tool" :aria-pressed="selected?.name === name" @click="choose(tool!)">
                <span class="tool-label"><strong>{{ tool?.title ?? name }}</strong><span v-if="commands.has(name)" class="cmd-badge" title="Has a slash command" aria-label="Has a slash command">/</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg></span><code>{{ name }}</code>
                <span v-if="tool?.description" class="tool-preview">{{ tool.description }}</span>
              </button>
            </li>
          </ul>
          <p v-if="names.length && !visibleTools.length" class="browser-note">No tools match your search.</p>
        </section>
        <section v-if="selected" class="tester" :aria-label="`Test ${selected.title}`" :aria-busy="running">
          <div class="tool-heading"><span class="eyebrow">Tool details</span><h4>{{ selected.title }}</h4><code>{{ selected.name }}</code><p v-if="commands.get(selected.name)" class="tool-command"><span class="muted">Slash command</span><code>{{ commands.get(selected.name) }}</code><CopyButton :text="commands.get(selected.name)!" label="Copy command" /></p><p v-if="selected.description" class="tool-description">{{ selected.description }}</p></div>
          <section class="parameters" aria-label="Parameters"><div class="section-heading"><h5>Parameters</h5><span class="muted">{{ running ? 'Running…' : canRun ? 'Ready to test' : 'Read-only' }}</span></div>
            <ToolRunForm v-if="canRun" :key="`${identity}:${selected.name}`" :schema="selected.inputSchema" :running="running" submit-label="Run tool" @run="run" />
            <p v-else class="muted">Testing requires Run tools access.</p>
          </section>
          <section class="output-panel" aria-label="Tool output"><div class="section-heading"><h5>Output</h5><span v-if="result" class="outcome" :class="{ failed: result.isError }">{{ result.isError ? 'Error' : 'Completed' }}</span></div>
            <ToolResultPanel v-if="result" :result="result" role="status" />
            <p v-else class="output-placeholder" role="status">{{ running ? 'Waiting for the tool to finish…' : 'Run this tool to see its result here.' }}</p>
          </section>
        <div class="integration-details"><slot /><slot name="reader" /></div>
        </section>
        <div v-else class="empty-selection">
          <span class="empty-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="m8 5 12 7-12 7z" /></svg></span>
          <h4>{{ privateExtension ? 'Available in chats' : !available ? 'Tools are unavailable' : !canBrowse ? 'Tool access required' : 'Choose a tool' }}</h4>
          <p v-if="privateExtension">Private extension tools run in your chats and always ask first.</p>
          <p v-else-if="!available">Bring this capability online or connect this extension to test its tools.</p>
          <p v-else-if="!canBrowse">Tool details require Browse tools or Run tools access.</p>
          <p v-else>Explore a tool’s details, enter its parameters, and view the result here.</p>
          <div class="integration-details"><slot /><slot name="reader" /></div>
        </div>
      </div>
    </div>
  </BaseModal>
</template>

<style scoped>
dialog.integration-modal { width: min(980px, calc(100vw - 48px)); height: min(720px, calc(100dvh - 64px)); max-height: calc(100dvh - 64px); padding: 0; overflow: hidden; background: var(--bg); }
.integration-modal :deep(> header) { height: 70px; box-sizing: border-box; margin: 0; padding: 20px 24px 16px; border-bottom: 1px solid var(--border); background: var(--surface); }
.integration-modal :deep(> header h3) { font-size: 1.2em; font-weight: 600; }
.integration-modal :deep(> header .close) { display: grid; place-items: center; width: 32px; height: 32px; border-radius: var(--radius-md); }
.integration-modal :deep(> header .close:hover) { color: var(--text); background: var(--bg); }
.tools-modal { height: calc(100% - 72px); display: flex; flex-direction: column; overflow: hidden; }
.integration-summary { flex-shrink: 0; display: flex; align-items: flex-start; gap: 14px; padding: 20px 24px; border-bottom: 1px solid var(--border); }
.integration-icon, .empty-icon { display: grid; place-items: center; width: 42px; height: 42px; flex-shrink: 0; border-radius: var(--radius-lg); color: var(--accent); background: color-mix(in srgb, var(--accent) 9%, var(--surface)); }
svg { width: 22px; height: 22px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.summary-copy { flex: 1; min-width: 0; }
.metadata { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; }
.kind { font-size: 0.85em; font-weight: 600; }
.identity, .tool-heading code { font-size: 0.8em; color: var(--muted); overflow-wrap: anywhere; }
.summary-description { font-size: 0.9em; color: var(--muted); overflow-wrap: anywhere; }
.summary-description :deep(p) { margin: 4px 0 0; }
.availability { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border: 1px solid var(--border); border-radius: var(--radius-full); font-size: 0.8em; color: var(--muted); white-space: nowrap; }
.availability.online { color: var(--success); background: color-mix(in srgb, var(--success) 6%, var(--bg)); }
.workspace { display: grid; grid-template-columns: 290px minmax(0, 1fr); flex: 1; min-height: 0; overflow: hidden; }
.tool-browser { display: flex; flex-direction: column; min-height: 0; overflow: hidden; min-width: 0; padding: 20px 14px; border-right: 1px solid var(--border); background: var(--surface); }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 14px; }
h4, h5, p { margin: 0; }
.section-heading h4, h5 { font-size: 0.9em; font-weight: 600; }
.section-heading > .muted { font-size: 0.75em; }
.tool-count { padding: 1px 7px; border-radius: var(--radius-sm); background: var(--code-bg); color: var(--muted); font-size: 0.75em; }
.tool-search { display: flex; align-items: center; gap: 8px; padding: 8px 10px; margin-bottom: 12px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg); }
.tool-search:focus-within { border-color: var(--accent); }
.tools-modal .tool-search input[type="search"]:focus-visible { outline: none; }
.tool-search svg { width: 16px; height: 16px; color: var(--muted); flex-shrink: 0; }
.tools-modal .tool-search input[type="search"] { width: 100%; min-width: 0; padding: 0; border: none; background: transparent; border-radius: 0; font-size: 0.85em; }
.browser-note { font-size: 0.85em; color: var(--muted); padding: 10px 4px; }
.tool-list { flex: 1; min-height: 0; list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; overflow-y: auto; overscroll-behavior: contain; }
.tool-list button { width: 100%; display: flex; flex-direction: column; align-items: stretch; gap: 5px; padding: 12px; border: 1px solid transparent; border-radius: var(--radius-lg); background: transparent; text-align: left; color: var(--text); font: inherit; cursor: pointer; transition: background 0.15s ease, border-color 0.15s ease; }
.tool-list button:disabled { cursor: default; opacity: .6; }
.tool-list button:hover { background: var(--bg); }
.tool-list button[aria-pressed=true] { border-color: color-mix(in srgb, var(--accent) 35%, var(--border)); background: color-mix(in srgb, var(--accent) 8%, var(--bg)); }
.tool-label { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 0.9em; }
.tool-label strong { font-weight: 500; overflow-wrap: anywhere; }
.tool-label svg { width: 15px; height: 15px; flex-shrink: 0; color: var(--muted); }
.tool-list code { font-size: 0.75em; color: var(--muted); overflow-wrap: anywhere; }
.tool-preview { font-size: 0.8em; line-height: 1.5; color: var(--muted); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; }
.tester { min-height: 0; overflow-y: auto; overscroll-behavior: contain; min-width: 0; padding: 24px; display: flex; flex-direction: column; gap: 22px; }
.eyebrow { display: block; font-size: 0.7em; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin-bottom: 6px; }
.tool-heading h4 { font-size: 1.15em; font-weight: 600; margin-bottom: 3px; overflow-wrap: anywhere; }
.cmd-badge { flex-shrink: 0; padding: 0 6px; border-radius: var(--radius-sm); font: 0.75em var(--mono); color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, var(--bg)); }
.tool-command { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 10px; font-size: 0.85em; }
.tool-command code { color: var(--text); background: var(--code-bg); padding: 1px 6px; border-radius: var(--radius-sm); }
.tool-description { margin-top: 12px; font-size: 0.9em; white-space: pre-wrap; color: var(--muted); overflow-wrap: anywhere; }
.parameters, .output-panel { border-top: 1px solid var(--border); padding-top: 18px; }
.outcome { color: var(--success); font-size: 0.75em; }
.outcome.failed { color: var(--danger); }
.result { padding: 12px 14px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface); }
.result strong { font-size: 0.8em; font-weight: 500; color: var(--muted); }
.result.failed { border-color: var(--danger); }
.result pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 280px; overflow-y: auto; margin: 8px 0 0; font: 0.85em/1.55 var(--mono); }
.output-placeholder { font-size: 0.85em; color: var(--muted); padding: 18px; background: var(--surface); border: 1px dashed var(--border); border-radius: var(--radius-lg); }
.integration-details { width: 100%; text-align: left; display: grid; gap: 12px; }
.empty-selection { min-height: 0; overflow-y: auto; display: flex; flex-direction: column; align-items: center; justify-content: flex-start; gap: 12px; padding: 40px 32px; text-align: center; }
.empty-selection h4 { font-size: 1em; font-weight: 600; }
.empty-selection p { max-width: 330px; color: var(--muted); font-size: 0.9em; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (max-width: 767px) {
  dialog.integration-modal { width: calc(100vw - 24px); height: calc(100dvh - var(--rail-height) - 24px); max-height: calc(100dvh - var(--rail-height) - 24px); }
  .integration-modal :deep(> header) { padding: 16px; }
  .integration-summary { display: grid; grid-template-columns: 42px minmax(0, 1fr); padding: 16px; gap: 10px; }
  .availability { grid-column: 2; margin-left: 0; justify-self: start; }
  .workspace { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(120px, 38%) minmax(0, 1fr); }
  .tool-browser { padding: 16px; border-right: none; border-bottom: 1px solid var(--border); }

  .tester { padding: 20px 16px; }
  .empty-selection { padding: 32px 20px; }
}
@media (prefers-reduced-motion: reduce) { .tool-list button { transition: none; } }
</style>
