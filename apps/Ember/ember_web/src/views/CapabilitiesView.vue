<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { commandsClient, type CapabilityInfo } from "../api/CommandsClient";
import { extensionsClient, type ExtensionInfo } from "../api/ExtensionsClient";
import { McpServerClient } from "../api/McpServerClient";
import type { ResourceInfo, ToolInfo } from "../api/types";
import CapabilityCard from "../components/CapabilityCard.vue";
import type { SectionPage } from "../components/CapabilitySection.vue";
import ResourceReader from "../components/ResourceReader.vue";
import SegmentedControl from "../components/SegmentedControl.vue";
import { useAccountCapabilitiesStore } from "../stores/accountCapabilities";
import { useAuthStore } from "../stores/auth";
import { useUserExtensionsStore } from "../stores/userExtensions";
import { addedOnly, groupTools, inExtensionNamespace } from "../utils/capabilityGroups";
import { matchesUserExtension, userExtensionSummary } from "../utils/userExtensions";
import { errorMessage } from "../utils/errors";
import { formatToolResult } from "../utils/toolResultFormat";
import { safeWebUrl } from "../utils/webUrl";

/** Account capabilities and extensions, shown as compact cards. Their modals
 * provide a tool browser, execution panel and resource reader. */

const auth = useAuthStore();
const account = useAccountCapabilitiesStore();
const userExt = useUserExtensionsStore();
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

// The resource being read and what came back.
const reading = ref<string | null>(null);
const readUri = ref("");
const readResult = ref<{ uri: string; text: string } | null>(null);
const readError = ref("");


// Capabilities, tools and resources need tools.view; extensions need only chat.use.
const canTools = computed(() => auth.hasPermission("tools.view"));
const showBuiltin = computed(() => canTools.value && kind.value !== "extensions");
const showExtensions = computed(() => kind.value !== "builtin");
// Headings tell the groups apart; only when both can show.
const groupHeadings = computed(() => canTools.value && kind.value === "all");
const added = computed(() =>
  addedOnly(capabilities.value, extensions.value, tools.value, account.capabilities, account.extensions),
);
const grouped = computed(() => groupTools(added.value.capabilities, added.value.tools, query.value, added.value.extensions));
// The account's own MCP servers that are on: they show with the extensions, as cards that only list
// their tools (their tools work for the agent, not on this page).
const privateShown = computed(() => userExt.items.filter((i) => i.enabled && matchesUserExtension(i, query.value)));
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
    (!showExtensions.value || (grouped.value.extensionGroups.length === 0 && privateShown.value.length === 0)),
);
// Nothing at all is added (not just filtered away): invite the user to the Supermarket.
const nothingAdded = computed(
  () =>
    added.value.capabilities.length === 0 &&
    added.value.extensions.length === 0 &&
    added.value.tools.length === 0 &&
    !userExt.items.some((i) => i.enabled),
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
    // Without tools.view only the extensions are listed.
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

function startRead(resource: ResourceInfo): void {
  readResult.value = null;
  readError.value = "";
  readUri.value = resource.uri;
  if (!resource.template) void read(resource.uri);
  else reading.value = resource.uri; // fill in the {placeholders} first

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

onMounted(() => {
  void load();
  // Each one's status comes from a live probe, so look again whenever the page opens.
  if (auth.hasPermission("chat.use")) void userExt.refresh();
});
</script>

<template>
  <section class="caps-view">
    <div class="column page-column">
      <div class="head">
        <h2 class="page-title">
          Capabilities <span v-if="added.tools.length" class="count">{{ added.tools.length }} tools</span>
        </h2>
        <div class="head-actions">
          <RouterLink to="/capabilities/supermarket" class="shop">Supermarket</RouterLink>
        </div>
      </div>
      <p class="muted intro page-description">What you've added: built-in capabilities and extensions. Open one to run its tools, or add more in the Supermarket.</p>
      <details class="how muted">
        <summary>How switches work</summary>
        <p>
          Each switch decides whether the agent and the <code>/</code> commands may use that capability or extension in
          your chats. What you've added follows your account to other devices. Turning one off here takes it off this
          page and puts it back in the Supermarket. Nothing is deleted.
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
      <p v-if="actionError || (account.ready && account.error) || userExt.error" class="error">
        {{ actionError || account.error || userExt.error }}
      </p>

      <div v-if="!loading && !loadError && account.ready" class="integration-grid">
        <p v-if="nothingShown && filtering" class="muted">Nothing matches "{{ query.trim() }}".</p>
        <div v-else-if="nothingShown && nothingAdded" class="empty">
          <p class="muted">Nothing added yet. Open the Supermarket to add capabilities and extensions.</p>
          <RouterLink to="/capabilities/supermarket" class="shop">Open the Supermarket</RouterLink>
        </div>
        <p v-else-if="nothingShown" class="muted">No capabilities, extensions or tools in this view.</p>

        <template v-if="showBuiltin">
          <h4 v-if="groupHeadings && grouped.groups.length" class="group-title">Built-in</h4>
          <div class="cards">
          <CapabilityCard
            v-for="g in grouped.groups"
            :key="g.capability.name"
            :label="g.capability.label ?? g.capability.name"
            :name="g.capability.name"
            icon="builtin"
            :tools="g.tools"
            :summary="capabilitySummary(g.capability, g.tools.length)"
            :status="g.capability.enabled ? 'ok' : 'off'"
            :dimmed="!g.capability.enabled"
            :page="capabilityPage(g.capability)"
            control="switch"
            :checked="true"
            scope="Account"
            switch-title="Turn off for your account. It moves back to the Supermarket."
            @switch="account.setCapability(g.capability.name, false)"
          >
            <p v-if="!g.capability.enabled" class="muted">Turned off for everyone: its tools and resources aren't offered to anyone.</p>
            <template v-else>
              <p v-if="g.tools.length === 0 && resourcesOf(g.capability).length === 0" class="muted">Nothing registered.</p>
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
            <template #reader>
              <ResourceReader v-model:uri="readUri" :reading="reading" :read-result="readResult" :read-error="readError" :text="readShown" @read="read" />
            </template>
          </CapabilityCard>
          </div>
        </template>

        <template v-if="showExtensions">
          <h4 v-if="groupHeadings && (grouped.extensionGroups.length || privateShown.length)" class="group-title">Extensions</h4>
          <div class="cards">
          <CapabilityCard
            v-for="g in grouped.extensionGroups"
            :key="g.extension.id"
            :label="g.extension.label"
            :name="g.extension.id"
            icon="extension"
            :tools="canTools ? g.tools : []"
            :names="g.extension.tools"
            :summary="extensionSummary(g)"
            :status="g.extension.status === 'connected' ? 'ok' : 'bad'"
            :page="extensionPage(g.extension)"
            control="switch"
            :checked="true"
            scope="Account"
            switch-title="Turn off for your account. It moves back to the Supermarket."
            @switch="account.setExtension(g.extension.id, false)"
          >
            <template #description><p>{{ g.extension.description || `Explore the tools provided by ${g.extension.label}.` }}</p></template>
            <p v-if="g.extension.status !== 'connected'" class="error">
              Not connected{{ g.extension.error ? `: ${g.extension.error}` : "" }}
            </p>
            <p
              v-else-if="canTools && g.tools.length === 0 && resourcesOfExtension(g.extension).length === 0"
              class="muted"
            >
              Nothing registered.
            </p>
            <p v-if="resourcesOfExtension(g.extension).length" class="res-label">Resources</p>
            <ul v-if="resourcesOfExtension(g.extension).length" class="resources">
              <li v-for="r in resourcesOfExtension(g.extension)" :key="r.uri">
                <svg class="res-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 2h5l3 3v9H4zM9 2v3h3" /></svg>
                <button type="button" class="link" @click="startRead(r)">{{ r.name }}</button>
                <code class="name">{{ r.uri }}</code>
                <span v-if="r.description" class="muted">{{ r.description }}</span>
              </li>
            </ul>
            <template #reader>
              <ResourceReader v-model:uri="readUri" :reading="reading" :read-result="readResult" :read-error="readError" :text="readShown" @read="read" />
            </template>
          </CapabilityCard>
          <CapabilityCard
            v-for="i in privateShown"
            :key="`private:${i.id}`"
            :label="i.label"
            :name="i.id"
            icon="extension"
            :names="i.tools"
            :summary="userExtensionSummary(i)"
            :status="i.status === 'connected' ? 'ok' : i.status === 'error' ? 'bad' : 'off'"
            control="switch"
            :checked="true"
            :locked="!auth.hasPermission('extensions.personal.manage')"
            scope="Private"
            switch-title="Turn off. It stays in your Supermarket under My extensions."
            @switch="userExt.setEnabled(i.id, false)"
          >
            <template #description><p>{{ i.description || "Tools for your private conversations." }}</p></template>
            <p v-if="i.status === 'error'" class="error">Not connected{{ i.error ? `: ${i.error}` : "" }}</p>
            <p v-else-if="i.status === 'unknown'" class="muted">{{ i.error ?? "Not checked yet" }}</p>
            <ul v-if="i.tools.length" class="private-tools">
              <li v-for="t in i.tools" :key="t"><code class="name">{{ t }}</code></li>
            </ul>
            <p class="muted">Its tools work in your chats and always ask first. They can't be run from this page.</p>
            <template #reader>
              <ResourceReader v-model:uri="readUri" :reading="reading" :read-result="readResult" :read-error="readError" :text="readShown" @read="read" />
            </template>
          </CapabilityCard>
          </div>
        </template>

        <h4 v-if="groupHeadings && showBuiltin && showOther" class="group-title">Other</h4>
        <div v-if="showBuiltin && showOther" class="cards">
        <CapabilityCard
          v-if="showBuiltin && showOther"
          label="Other tools"
          name="extensions"
          icon="other"
          :tools="grouped.otherTools"
          :summary="countText(grouped.otherTools.length, filtering ? 0 : otherResources.length)"
        >
          <p v-if="!filtering && otherResources.length" class="res-label">Resources</p>
          <ul v-if="!filtering && otherResources.length" class="resources">
            <li v-for="r in otherResources" :key="r.uri">
              <svg class="res-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 2h5l3 3v9H4zM9 2v3h3" /></svg>
              <button type="button" class="link" @click="startRead(r)">{{ r.name }}</button>
              <code class="name">{{ r.uri }}</code>
            </li>
          </ul>
          <template #reader>
            <ResourceReader v-model:uri="readUri" :reading="reading" :read-result="readResult" :read-error="readError" :text="readShown" @read="read" />
            </template>
          </CapabilityCard>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 270px), 1fr)); grid-auto-rows: 1fr; gap: 14px; }
.caps-view {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
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
.private-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  margin: 0;
  padding: 0;
  list-style: none;
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
.muted {
  color: var(--muted);
}
.error {
  color: var(--danger);
}
</style>
