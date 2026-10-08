<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useTemplateRef } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { commandsClient, type CapabilityInfo } from "../api/CommandsClient";
import { extensionsClient, type ExtensionInfo } from "../api/ExtensionsClient";
import { McpServerClient } from "../api/McpServerClient";
import type { ResourceInfo, ToolInfo, ToolRunResult } from "../api/types";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import CapabilitySection, { type SectionPage } from "../components/CapabilitySection.vue";
import MarkdownContent from "../components/MarkdownContent.vue";
import SegmentedControl from "../components/SegmentedControl.vue";
import ToolCard from "../components/ToolCard.vue";
import ToolRunModal from "../components/ToolRunModal.vue";
import { useEveryoneSwitch } from "../composables/useEveryoneSwitch";
import { useAccountCapabilitiesStore } from "../stores/accountCapabilities";
import { useAuthStore } from "../stores/auth";
import { addedOnly, groupTools, inExtensionNamespace } from "../utils/capabilityGroups";
import { errorMessage } from "../utils/errors";
import { formatToolResult } from "../utils/toolResultFormat";
import { safeWebUrl } from "../utils/webUrl";

/** What the account has added from the Supermarket, as one list of identical
 * cards: built-in capabilities and extensions (other MCP servers). Each card
 * brings tools (run them in place) and resources to read, may have an Open
 * button, and has a switch: turning it off removes the card (the item goes back
 * to the Supermarket). Admins can also turn a built-in capability off for
 * everyone, from inside its card. Collapsed by default, opened while a filter is
 * typed. A tool is a row (label and name); a click opens its description and
 * run form in a modal. */

const auth = useAuthStore();
const account = useAccountCapabilitiesStore();
const server = new McpServerClient();

const capabilities = ref<CapabilityInfo[]>([]);
const tools = ref<ToolInfo[]>([]);
const resources = ref<ResourceInfo[]>([]);
const extensions = ref<ExtensionInfo[]>([]);
const loading = ref(true);
const loadError = ref("");
const actionError = ref("");
// Which kind of card is listed.
type Kind = "all" | "builtin" | "extensions";
const kind = ref<Kind>("all");

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
// Capabilities, tools and resources need tools.use; extensions need only chat.use.
const canTools = computed(() => auth.hasPermission("tools.use"));
const showBuiltin = computed(() => canTools.value && kind.value !== "extensions");
const showExtensions = computed(() => kind.value !== "builtin");
// Headings tell the groups apart; only when both can show.
const groupHeadings = computed(() => canTools.value && kind.value === "all");
const added = computed(() =>
  addedOnly(capabilities.value, extensions.value, tools.value, account.capabilities, account.extensions),
);
const grouped = computed(() => groupTools(added.value.capabilities, added.value.tools, query.value, added.value.extensions));
const selectedTool = computed(() => tools.value.find((t) => t.name === openTool.value) ?? null);
// The account's choices load beside the page's own data.
const accountLoading = computed(() => !account.ready && account.error === "");

/** Resources no capability claims (of every capability, added or not). */
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

const extensionKey = (id: string): string => `\0ext:${id}`;
function resourcesOfExtension(extension: ExtensionInfo): ResourceInfo[] {
  return filtering.value ? [] : (extensionResources.value.get(extension.id) ?? []);
}

function resourcesOf(capability: CapabilityInfo): ResourceInfo[] {
  const names = new Set(capability.resources);
  return resources.value.filter((r) => names.has(r.name) || names.has(r.uri));
}

const nothingShown = computed(
  () =>
    (!showBuiltin.value || (grouped.value.groups.length === 0 && !showOther.value)) &&
    (!showExtensions.value || grouped.value.extensionGroups.length === 0),
);
// Nothing at all is added (not just filtered away): invite the user to the Supermarket.
const nothingAdded = computed(
  () => added.value.capabilities.length === 0 && added.value.extensions.length === 0 && added.value.tools.length === 0,
);

const countText = (tools: number, resources: number): string =>
  `${tools} tool${tools === 1 ? "" : "s"}${resources ? ` · ${resources} resource${resources === 1 ? "" : "s"}` : ""}`;

function capabilitySummary(capability: CapabilityInfo, tools: number): string {
  return capability.enabled ? countText(tools, resourcesOf(capability).length) : "off";
}

/** Where a capability's Open button leads: its own page, while it is on. */
function capabilityPage(capability: CapabilityInfo): SectionPage | null {
  return capability.has_gui && capability.enabled
    ? { to: `/capabilities/${encodeURIComponent(capability.name)}`, external: false }
    : null;
}

/** Where an extension's Open button leads: its own web UI when it names a
 * usable one (a new tab), else nowhere (its tools are listed in its card). */
function extensionPage(e: ExtensionInfo): SectionPage | null {
  const web = safeWebUrl(e.web_url);
  return web ? { to: web, external: true, label: "Open app" } : null;
}

function extensionSummary(g: { extension: ExtensionInfo; tools: ToolInfo[] }): string {
  if (g.extension.status !== "connected") return "Not connected";
  return countText(canTools.value ? g.tools.length : g.extension.tools.length, resourcesOfExtension(g.extension).length);
}

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    // Without tools.use only the extensions are listed.
    const [caps, toolList, res, exts] = await Promise.all([
      canTools.value ? commandsClient.capabilities() : [],
      canTools.value ? server.listTools() : [],
      canTools.value ? server.listResources().catch(() => [] as ResourceInfo[]) : [],
      // Without it the extension tools would sit under "Other tools".
      canTools.value ? extensionsClient.list().catch(() => [] as ExtensionInfo[]) : extensionsClient.list(),
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

// Switching a capability for everyone reaches every mcp_server client, so it
// asks first, in the confirmation dialog (turning one off is the riskier way round).
const {
  pending: pendingSwitch,
  switching,
  error: switchError,
  copy: switchCopy,
  ask: askSwitch,
  cancel: cancelSwitch,
  confirm: confirmSwitch,
} = useEveryoneSwitch(async (updated) => {
  capabilities.value = capabilities.value.map((c) => (c.name === updated.name ? updated : c));
  // Switching changes which tools and resources the server offers.
  const [toolList, res] = await Promise.all([
    server.listTools().catch(() => tools.value),
    server.listResources().catch(() => resources.value),
  ]);
  tools.value = [...toolList].sort((a, b) => a.title.localeCompare(b.title));
  resources.value = res;
});

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
          Capabilities <span v-if="added.tools.length" class="count">{{ added.tools.length }} tools</span>
        </h2>
        <div class="head-actions">
          <RouterLink to="/capabilities/supermarket" class="shop">Supermarket</RouterLink>
        </div>
      </div>
      <p class="muted intro">What you've added: built-in capabilities and extensions. Open one to run its tools, or add more in the Supermarket.</p>
      <details class="how muted">
        <summary>How switches work</summary>
        <p>
          Each switch decides whether the agent and the <code>/</code> commands may use that capability or extension in
          your chats. What you've added follows your account to other devices. Turning one off here takes it off this
          page and puts it back in the Supermarket. Nothing is deleted. Admins can also turn a built-in capability off for
          everyone, from inside its card.
        </p>
      </details>
      <div v-if="!loading && !loadError" class="toolbar">
        <label class="search-box">
          <svg class="search-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
            <path d="M7 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10M11 11l3.5 3.5" />
          </svg>
          <input v-model="query" type="search" class="search" placeholder="Filter tools" aria-label="Filter tools" />
        </label>
        <SegmentedControl
          v-if="canTools"
          v-model="kind"
          class="kinds"
          aria-label="Show"
          :options="[
            { value: 'all', label: 'All' },
            { value: 'builtin', label: 'Built-in' },
            { value: 'extensions', label: 'Extensions' },
          ]"
        />
      </div>

      <p v-if="loading || accountLoading" class="muted">loading ...</p>
      <p v-else-if="loadError" class="error">error: {{ loadError }}</p>
      <p v-else-if="!account.ready" class="error">error: {{ account.error }}</p>
      <p v-if="actionError || switchError || (account.ready && account.error)" class="error">
        {{ actionError || switchError || account.error }}
      </p>

      <template v-if="!loading && !loadError && account.ready">
        <p v-if="nothingShown && filtering" class="muted">Nothing matches "{{ query.trim() }}".</p>
        <div v-else-if="nothingShown && nothingAdded" class="empty">
          <p class="muted">Nothing added yet. Open the Supermarket to add capabilities and extensions.</p>
          <RouterLink to="/capabilities/supermarket" class="shop">Open the Supermarket</RouterLink>
        </div>
        <p v-else-if="nothingShown" class="muted">No capabilities, extensions or tools in this view.</p>

        <template v-if="showBuiltin">
          <h4 v-if="groupHeadings && grouped.groups.length" class="group-title">Built-in</h4>
          <CapabilitySection
            v-for="g in grouped.groups"
            :key="g.capability.name"
            :label="g.capability.label ?? g.capability.name"
            :name="g.capability.name"
            icon="builtin"
            :open="isOpen(g.capability.name)"
            :summary="capabilitySummary(g.capability, g.tools.length)"
            :status="g.capability.enabled ? 'ok' : 'off'"
            :dimmed="!g.capability.enabled"
            :page="capabilityPage(g.capability)"
            control="switch"
            :checked="true"
            scope="Account"
            switch-title="Turn off for your account. It moves back to the Supermarket."
            @toggle="toggleSection(g.capability.name)"
            @switch="account.setCapability(g.capability.name, false)"
          >
            <p v-if="!g.capability.enabled" class="muted">Turned off for everyone: its tools and resources aren't offered to anyone.</p>
            <template v-else>
              <p v-if="g.tools.length === 0 && resourcesOf(g.capability).length === 0" class="muted">Nothing registered.</p>
              <ul v-if="g.tools.length" class="cards">
                <ToolCard v-for="t in g.tools" :key="t.name" :tool="t" @open="openToolModal(t.name)" />
              </ul>
              <p v-if="resourcesOf(g.capability).length" class="res-label">Resources</p>
              <ul v-if="resourcesOf(g.capability).length" class="resources">
                <li v-for="r in resourcesOf(g.capability)" :key="r.uri">
                  <svg class="res-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 2h5l3 3v9H4zM9 2v3h3" /></svg>
                  <button type="button" class="link" @click="startRead(r)">{{ r.name }}</button>
                  <code class="name">{{ r.uri }}</code>
                  <span v-if="r.description" class="muted">{{ r.description }}</span>
                </li>
              </ul>
            </template>
            <div v-if="isAdmin" class="card-foot">
              <button
                type="button"
                class="everyone"
                :disabled="switching === g.capability.name"
                @click="askSwitch(g.capability)"
              >
                {{ g.capability.enabled ? "Turn off for everyone" : "Turn on for everyone" }}
              </button>
            </div>
          </CapabilitySection>
        </template>

        <template v-if="showExtensions">
          <h4 v-if="groupHeadings && grouped.extensionGroups.length" class="group-title">Extensions</h4>
          <CapabilitySection
            v-for="g in grouped.extensionGroups"
            :key="g.extension.id"
            :label="g.extension.label"
            :name="g.extension.id"
            icon="extension"
            :open="isOpen(extensionKey(g.extension.id))"
            :summary="extensionSummary(g)"
            :status="g.extension.status === 'connected' ? 'ok' : 'bad'"
            :page="extensionPage(g.extension)"
            control="switch"
            :checked="true"
            scope="Account"
            switch-title="Turn off for your account. It moves back to the Supermarket."
            @toggle="toggleSection(extensionKey(g.extension.id))"
            @switch="account.setExtension(g.extension.id, false)"
          >
            <p v-if="g.extension.description" class="muted">{{ g.extension.description }}</p>
            <p v-if="g.extension.status !== 'connected'" class="error">
              Not connected{{ g.extension.error ? `: ${g.extension.error}` : "" }}
            </p>
            <p
              v-else-if="canTools && g.tools.length === 0 && resourcesOfExtension(g.extension).length === 0"
              class="muted"
            >
              Nothing registered.
            </p>
            <ul v-if="canTools && g.tools.length" class="cards">
              <ToolCard v-for="t in g.tools" :key="t.name" :tool="t" @open="openToolModal(t.name)" />
            </ul>
            <p v-if="resourcesOfExtension(g.extension).length" class="res-label">Resources</p>
            <ul v-if="resourcesOfExtension(g.extension).length" class="resources">
              <li v-for="r in resourcesOfExtension(g.extension)" :key="r.uri">
                <svg class="res-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 2h5l3 3v9H4zM9 2v3h3" /></svg>
                <button type="button" class="link" @click="startRead(r)">{{ r.name }}</button>
                <code class="name">{{ r.uri }}</code>
                <span v-if="r.description" class="muted">{{ r.description }}</span>
              </li>
            </ul>
          </CapabilitySection>
        </template>

        <h4 v-if="groupHeadings && showBuiltin && showOther" class="group-title">Other</h4>
        <CapabilitySection
          v-if="showBuiltin && showOther"
          label="Other tools"
          name="extensions"
          icon="other"
          :open="isOpen(OTHER)"
          :summary="countText(grouped.otherTools.length, filtering ? 0 : otherResources.length)"
          @toggle="toggleSection(OTHER)"
        >
          <ul v-if="grouped.otherTools.length" class="cards">
            <ToolCard v-for="t in grouped.otherTools" :key="t.name" :tool="t" @open="openToolModal(t.name)" />
          </ul>
          <p v-if="!filtering && otherResources.length" class="res-label">Resources</p>
          <ul v-if="!filtering && otherResources.length" class="resources">
            <li v-for="r in otherResources" :key="r.uri">
              <svg class="res-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 2h5l3 3v9H4zM9 2v3h3" /></svg>
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
      @confirm="confirmSwitch"
      @close="cancelSwitch"
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
.head-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.shop {
  padding: 6px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  font-size: 0.9em;
  color: var(--text);
  text-decoration: none;
}
.shop:hover {
  border-color: var(--accent);
}
.shop:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.empty {
  display: grid;
  justify-items: start;
  gap: 10px;
}

.toolbar {
  align-items: last baseline;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  margin-bottom: 16px;
}
.search-box {
  position: relative;
  flex: 1 1 220px;
}
.search-icon {
  position: absolute;
  top: 50%;
  left: 12px;
  transform: translateY(-50%);
  fill: none;
  stroke: var(--muted);
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
  pointer-events: none;
}
.how {
  margin: 0 0 12px;
  font-size: 0.85em;
}
.how summary {
  width: fit-content;
  cursor: pointer;
  color: var(--accent);
}
.how p {
  margin: 6px 0 0;
}
.group-title {
  margin: 16px 2px 8px;
  font-size: 0.8em;
  font-weight: 500;
}
.group-title .muted {
  font-weight: 400;
}
.res-label {
  margin: 4px 0 0;
  font-size: 0.75em;
  color: var(--muted);
}
.res-icon {
  flex-shrink: 0;
  align-self: center;
  fill: none;
  stroke: var(--muted);
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.card-foot {
  display: flex;
  justify-content: flex-end;
}
.everyone {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  cursor: pointer;
  font-size: 0.85em;
  color: var(--muted);
  background: transparent;
}
.everyone:hover:not(:disabled) {
  color: var(--text);
  border-color: var(--accent);
}
.everyone:disabled {
  cursor: default;
  opacity: 0.5;
}
.search {
  box-sizing: border-box;
  width: 100%;
  padding: 7px 12px 7px 32px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
}
.search:focus {
  outline: none;
  border-color: var(--accent);
}
.intro {
  margin: 0 0 8px;
  font-size: 0.9em;
}
/* One bordered list of tool rows, not a box per tool. */
.cards {
  margin: 0;
  padding: 0;
  overflow: hidden;
  list-style: none;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
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
