<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useTemplateRef } from "vue";
import { useRoute } from "vue-router";
import { commandsClient, type CapabilityInfo } from "../api/CommandsClient";
import { extensionsClient, type ExtensionInfo } from "../api/ExtensionsClient";
import { McpServerClient } from "../api/McpServerClient";
import type { ResourceInfo, ToolInfo, ToolRunResult } from "../api/types";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import CapabilitySection from "../components/CapabilitySection.vue";
import MarkdownContent from "../components/MarkdownContent.vue";
import OpenPageButton from "../components/OpenPageButton.vue";
import ToolCard from "../components/ToolCard.vue";
import ToolRunModal from "../components/ToolRunModal.vue";
import { useAuthStore } from "../stores/auth";
import { groupTools, inExtensionNamespace } from "../utils/capabilityGroups";
import { errorMessage } from "../utils/errors";
import { formatToolResult } from "../utils/toolResultFormat";
import { safeWebUrl } from "../utils/webUrl";

/** mcp_server's built-in capabilities, each with the tools it brings (run
 * them in place) and its resources to read; admins can switch a capability on
 * or off for every mcp_server client. The old Tools and Capabilities pages in
 * one: collapsed by default, opened while a filter is typed. A tool is a row
 * (label and name); a click opens its description and run form in a modal. */

const auth = useAuthStore();
const server = new McpServerClient();

const capabilities = ref<CapabilityInfo[]>([]);
const tools = ref<ToolInfo[]>([]);
const resources = ref<ResourceInfo[]>([]);
const extensions = ref<ExtensionInfo[]>([]);
const loading = ref(true);
const loadError = ref("");
const actionError = ref("");
const switching = ref<string | null>(null);

// ?q= prefills the filter (links to a single tool use it).
const initialQuery = useRoute().query.q;
const query = ref(typeof initialQuery === "string" ? initialQuery : "");
const filtering = computed(() => query.value.trim() !== "");

/** Which sections the user opened; while filtering, every shown one is open. */
const openSections = ref(new Set<string>());
const OTHER = "\0other";
function isOpen(key: string): boolean {
  return filtering.value || openSections.value.has(key);
}
function toggleSection(key: string): void {
  const next = new Set(openSections.value);
  if (!next.delete(key)) next.add(key);
  openSections.value = next;
}

// The tool whose modal is open; its last result stays until re-run or closed.
const openTool = ref<string | null>(null);
const running = ref(false);
const result = ref<ToolRunResult | null>(null);

// The resource being read and what came back.
const reading = ref<string | null>(null);
const readUri = ref("");
const readResult = ref<{ uri: string; text: string } | null>(null);
const readError = ref("");
const reader = useTemplateRef<HTMLElement>("reader");

const isAdmin = computed(() => auth.hasPermission("admin.manage"));
const grouped = computed(() => groupTools(capabilities.value, tools.value, query.value, extensions.value));
const selectedTool = computed(() => tools.value.find((t) => t.name === openTool.value) ?? null);

/** Resources no capability claims. */
const unclaimedResources = computed(() => {
  const claimed = new Set(capabilities.value.flatMap((c) => c.resources));
  return resources.value.filter((r) => !claimed.has(r.name) && !claimed.has(r.uri));
});
/** Those namespaced under an extension ("<id>__<name>") belong to it. */
const extensionResources = computed(() => {
  const owned = new Map<string, ResourceInfo[]>();
  for (const e of extensions.value) {
    owned.set(e.id, unclaimedResources.value.filter((r) => inExtensionNamespace(e.id, r.name)));
  }
  return owned;
});
const otherResources = computed(() => {
  const owned = new Set([...extensionResources.value.values()].flat());
  return unclaimedResources.value.filter((r) => !owned.has(r));
});
const showOther = computed(() => grouped.value.otherTools.length > 0 || (!filtering.value && otherResources.value.length > 0));
const otherCapability: CapabilityInfo = { name: "extensions", label: "Other tools", enabled: true, tools: [], resources: [] };

/** An extension drawn as a capability card; it has no on/off switch here. */
function extensionCapability(extension: ExtensionInfo): CapabilityInfo {
  return { name: extension.id, label: extension.label, enabled: true, tools: [], resources: [] };
}
const extensionKey = (id: string): string => `\0ext:${id}`;
function resourcesOfExtension(extension: ExtensionInfo): ResourceInfo[] {
  return filtering.value ? [] : (extensionResources.value.get(extension.id) ?? []);
}

function resourcesOf(capability: CapabilityInfo): ResourceInfo[] {
  const names = new Set(capability.resources);
  return resources.value.filter((r) => names.has(r.name) || names.has(r.uri));
}

const nothingShown = computed(
  () => grouped.value.groups.length === 0 && grouped.value.extensionGroups.length === 0 && !showOther.value,
);

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    const [caps, toolList, res, exts] = await Promise.all([
      commandsClient.capabilities(),
      server.listTools(),
      server.listResources().catch(() => [] as ResourceInfo[]),
      // Only for grouping: without it the extension tools sit under "Other tools".
      extensionsClient.list().catch(() => [] as ExtensionInfo[]),
    ]);
    capabilities.value = caps;
    tools.value = [...toolList].sort((a, b) => a.title.localeCompare(b.title));
    resources.value = res;
    extensions.value = exts;
  } catch (err) {
    loadError.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

// Switching a capability reaches every mcp_server client, so it asks first, in
// the confirmation dialog (turning one off is the riskier way round).
const pendingSwitch = ref<CapabilityInfo | null>(null);

const switchCopy = computed(() => {
  const capability = pendingSwitch.value;
  if (!capability) return { title: "", message: "", label: "" };
  const verb = capability.enabled ? "Turn off" : "Turn on";
  return {
    title: `${verb} capability`,
    message: `${verb} "${capability.label ?? capability.name}" for every mcp_server client (chat_app, agents, ember)?`,
    label: verb,
  };
});

function toggleCapability(capability: CapabilityInfo): void {
  pendingSwitch.value = capability;
}

async function runSwitch(): Promise<void> {
  const capability = pendingSwitch.value;
  pendingSwitch.value = null;
  if (!capability) return;
  const next = !capability.enabled;
  actionError.value = "";
  switching.value = capability.name;
  try {
    const updated = await commandsClient.setCapability(capability.name, next);
    capabilities.value = capabilities.value.map((c) => (c.name === updated.name ? updated : c));
    // Switching changes which tools and resources the server offers.
    const [toolList, res] = await Promise.all([
      server.listTools().catch(() => tools.value),
      server.listResources().catch(() => resources.value),
    ]);
    tools.value = [...toolList].sort((a, b) => a.title.localeCompare(b.title));
    resources.value = res;
  } catch (err) {
    actionError.value = errorMessage(err);
  } finally {
    switching.value = null;
  }
}

function openToolModal(name: string): void {
  openTool.value = name;
  result.value = null;
}

async function run(name: string, args: Record<string, unknown>): Promise<void> {
  running.value = true;
  result.value = null;
  try {
    const outcome = await server.runTool(name, args);
    // The modal was closed (or another tool opened) while it ran: drop the result.
    if (openTool.value === name) result.value = outcome;
  } catch (err) {
    // Transport/protocol failure - shown the same way as a tool-side error.
    if (openTool.value === name) result.value = { text: String(err), isError: true };
  } finally {
    running.value = false;
  }
}

function startRead(resource: ResourceInfo): void {
  readResult.value = null;
  readError.value = "";
  readUri.value = resource.uri;
  if (!resource.template) void read(resource.uri);
  else reading.value = resource.uri; // fill in the {placeholders} first
  // The reader sits below the list: bring it into view.
  void nextTick(() => reader.value?.scrollIntoView?.({ block: "nearest" }));
}

async function read(uri: string): Promise<void> {
  reading.value = uri;
  readError.value = "";
  try {
    readResult.value = { uri, text: await server.readResource(uri) };
    reading.value = null;
  } catch (err) {
    readError.value = errorMessage(err);
  }
}

/** Shown formatted when it's a JSON object, else as Markdown text. */
const readShown = computed(() => (readResult.value ? (formatToolResult(readResult.value.text) ?? readResult.value.text) : ""));

onMounted(load);
</script>

<template>
  <section class="caps-view">
    <div class="column">
      <div class="head">
        <h2>
          Capabilities <span v-if="tools.length" class="count">{{ tools.length }} tools</span>
        </h2>
        <input v-if="!loading && !loadError" v-model="query" type="search" class="search" placeholder="Filter tools" />
      </div>
      <p class="muted intro">
        What mcp_server can do, grouped by capability. Open one to run its tools and read its resources. You can also
        run tools with <code>/</code> commands in the chat.
      </p>

      <p v-if="loading" class="muted">loading ...</p>
      <p v-else-if="loadError" class="error">error: {{ loadError }}</p>
      <p v-if="actionError" class="error">{{ actionError }}</p>

      <template v-if="!loading && !loadError">
        <p v-if="nothingShown && filtering" class="muted">Nothing matches "{{ query.trim() }}".</p>
        <p v-else-if="nothingShown" class="muted">No capabilities or tools exposed.</p>

        <CapabilitySection
          v-for="g in grouped.groups"
          :key="g.capability.name"
          :capability="g.capability"
          :open="isOpen(g.capability.name)"
          :tool-count="g.tools.length"
          :resource-count="resourcesOf(g.capability).length"
          :is-admin="isAdmin"
          :switching="switching === g.capability.name"
          @toggle="toggleSection(g.capability.name)"
          @switch="toggleCapability(g.capability)"
        >
          <p v-if="!g.capability.enabled" class="muted">Turned off: its tools and resources aren't offered to anyone.</p>
          <template v-else>
            <p v-if="g.tools.length === 0 && resourcesOf(g.capability).length === 0" class="muted">Nothing registered.</p>
            <ul v-if="g.tools.length" class="cards">
              <ToolCard v-for="t in g.tools" :key="t.name" :tool="t" @open="openToolModal(t.name)" />
            </ul>
            <ul v-if="resourcesOf(g.capability).length" class="resources">
              <li v-for="r in resourcesOf(g.capability)" :key="r.uri">
                <button type="button" class="link" @click="startRead(r)">{{ r.name }}</button>
                <code class="name">{{ r.uri }}</code>
                <span v-if="r.description" class="muted">{{ r.description }}</span>
              </li>
            </ul>
          </template>
        </CapabilitySection>

        <CapabilitySection
          v-for="g in grouped.extensionGroups"
          :key="g.extension.id"
          :capability="extensionCapability(g.extension)"
          :open="isOpen(extensionKey(g.extension.id))"
          :tool-count="g.tools.length"
          :resource-count="resourcesOfExtension(g.extension).length"
          :is-admin="false"
          :switching="false"
          hide-state
          @toggle="toggleSection(extensionKey(g.extension.id))"
        >
          <p v-if="g.extension.status === 'error'" class="error">
            Not connected{{ g.extension.error ? `: ${g.extension.error}` : "" }}
          </p>
          <p v-else-if="g.tools.length === 0 && resourcesOfExtension(g.extension).length === 0" class="muted">
            Nothing registered.
          </p>
          <OpenPageButton
            v-if="safeWebUrl(g.extension.web_url)"
            class="open-app"
            :to="safeWebUrl(g.extension.web_url)!"
            external
            label="Open app"
          />
          <ul v-if="g.tools.length" class="cards">
            <ToolCard v-for="t in g.tools" :key="t.name" :tool="t" @open="openToolModal(t.name)" />
          </ul>
          <ul v-if="resourcesOfExtension(g.extension).length" class="resources">
            <li v-for="r in resourcesOfExtension(g.extension)" :key="r.uri">
              <button type="button" class="link" @click="startRead(r)">{{ r.name }}</button>
              <code class="name">{{ r.uri }}</code>
              <span v-if="r.description" class="muted">{{ r.description }}</span>
            </li>
          </ul>
        </CapabilitySection>

        <CapabilitySection
          v-if="showOther"
          :capability="otherCapability"
          :open="isOpen(OTHER)"
          :tool-count="grouped.otherTools.length"
          :resource-count="filtering ? 0 : otherResources.length"
          :is-admin="false"
          :switching="false"
          hide-state
          @toggle="toggleSection(OTHER)"
        >
          <ul v-if="grouped.otherTools.length" class="cards">
            <ToolCard v-for="t in grouped.otherTools" :key="t.name" :tool="t" @open="openToolModal(t.name)" />
          </ul>
          <ul v-if="!filtering && otherResources.length" class="resources">
            <li v-for="r in otherResources" :key="r.uri">
              <button type="button" class="link" @click="startRead(r)">{{ r.name }}</button>
              <code class="name">{{ r.uri }}</code>
            </li>
          </ul>
        </CapabilitySection>

        <section v-if="reading || readResult || readError" ref="reader" class="reader">
          <form v-if="reading" class="uri" @submit.prevent="read(readUri)">
            <label>
              URI
              <input v-model="readUri" type="text" spellcheck="false" />
            </label>
            <button class="primary">Read</button>
          </form>
          <p v-if="readError" class="error">{{ readError }}</p>
          <template v-if="readResult">
            <h3><code>{{ readResult.uri }}</code></h3>
            <MarkdownContent :text="readShown" />
          </template>
        </section>
      </template>
    </div>

    <ConfirmModal
      v-if="pendingSwitch"
      open
      :title="switchCopy.title"
      :message="switchCopy.message"
      :confirm-label="switchCopy.label"
      :danger="pendingSwitch.enabled"
      @confirm="runSwitch"
      @close="pendingSwitch = null"
    />

    <ToolRunModal
      :tool="selectedTool"
      :running="running"
      :result="result"
      @close="openTool = null"
      @run="(args) => selectedTool && run(selectedTool.name, args)"
    />
  </section>
</template>

<style scoped>
.caps-view {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.column {
  max-width: 820px;
  margin: 0 auto;
  padding: 24px 16px;
}
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}
h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 1.2em;
}
h3 {
  margin: 0;
  font-size: 1em;
}
.count {
  padding: 1px 8px;
  border-radius: var(--radius-full);
  font-size: 0.7em;
  font-weight: 400;
  color: var(--muted);
  background: var(--surface);
}
.search {
  flex: 0 1 260px;
  min-width: 0;
  padding: 7px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  background: var(--surface);
}
.search:focus {
  outline: none;
  border-color: var(--accent);
}
.intro {
  margin: 0 0 16px;
  font-size: 0.9em;
}
.cards {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.resources {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.resources li {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 10px;
  font-size: 0.9em;
}
.name {
  font-family: var(--mono);
  font-size: 0.8em;
  color: var(--muted);
  overflow-wrap: anywhere;
}
.open-app {
  justify-self: start;
}
.link {
  padding: 0;
  border: none;
  cursor: pointer;
  color: var(--accent);
  background: transparent;
  font: inherit;
  text-decoration: underline;
}
.reader {
  margin-top: 16px;
  padding: 12px 14px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-lg);
}
.uri {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 8px;
  margin-bottom: 10px;
}
.uri label {
  display: grid;
  flex: 1 1 260px;
  gap: 4px;
  font-size: 0.85em;
}
.uri input {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
  font-family: var(--mono);
}
.primary {
  padding: 6px 16px;
  border: none;
  border-radius: var(--radius-full);
  cursor: pointer;
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.muted {
  color: var(--muted);
}
.error {
  color: var(--danger);
}
</style>
