<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { commandsClient, type CapabilityInfo } from "../api/CommandsClient";
import { McpServerClient } from "../api/McpServerClient";
import type { ResourceInfo } from "../api/types";
import MarkdownContent from "../components/MarkdownContent.vue";
import { useAuthStore } from "../stores/auth";
import { errorMessage } from "../utils/errors";
import { formatToolResult } from "../utils/toolResultFormat";
import { toolTitle } from "../utils/toolTitles";

/** mcp_server's built-in capabilities: which tools and resources each
 * brings, their resources to read, and (admins) switching one on or off
 * for every mcp_server client (port of chat_app's Capabilities page). */

const auth = useAuthStore();
const server = new McpServerClient();

const capabilities = ref<CapabilityInfo[]>([]);
const resources = ref<ResourceInfo[]>([]);
const loading = ref(true);
const loadError = ref("");
const actionError = ref("");
const switching = ref<string | null>(null);

// The resource being read and what came back.
const reading = ref<string | null>(null);
const readUri = ref("");
const readResult = ref<{ uri: string; text: string } | null>(null);
const readError = ref("");

const isAdmin = computed(() => auth.hasPermission("admin.manage"));

/** Resources no capability claims (from extensions), shown on their own. */
const otherResources = computed(() => {
  const claimed = new Set(capabilities.value.flatMap((c) => c.resources));
  return resources.value.filter((r) => !claimed.has(r.name) && !claimed.has(r.uri));
});

function resourcesOf(capability: CapabilityInfo): ResourceInfo[] {
  const names = new Set(capability.resources);
  return resources.value.filter((r) => names.has(r.name) || names.has(r.uri));
}

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    const [caps, res] = await Promise.all([
      commandsClient.capabilities(),
      server.listResources().catch(() => [] as ResourceInfo[]),
    ]);
    capabilities.value = caps;
    resources.value = res;
  } catch (err) {
    loadError.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

async function toggle(capability: CapabilityInfo): Promise<void> {
  const next = !capability.enabled;
  const verb = next ? "Turn on" : "Turn off";
  if (!confirm(`${verb} "${capability.label ?? capability.name}" for every mcp_server client (chat_app, agents, ember)?`)) {
    return;
  }
  actionError.value = "";
  switching.value = capability.name;
  try {
    const updated = await commandsClient.setCapability(capability.name, next);
    capabilities.value = capabilities.value.map((c) => (c.name === updated.name ? updated : c));
    resources.value = await server.listResources().catch(() => resources.value);
  } catch (err) {
    actionError.value = errorMessage(err);
  } finally {
    switching.value = null;
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

onMounted(load);
</script>

<template>
  <section class="caps-view">
    <div class="column">
      <h2>Capabilities</h2>
      <p class="muted intro">
        What mcp_server can do, grouped by capability. Run tools on the
        <RouterLink to="/tools">Tools</RouterLink> page or with <code>/</code> commands in the chat.
      </p>

      <p v-if="loading" class="muted">loading ...</p>
      <p v-else-if="loadError" class="error">error: {{ loadError }}</p>
      <p v-if="actionError" class="error">{{ actionError }}</p>

      <article v-for="c in capabilities" :key="c.name" :class="['card', { off: !c.enabled }]">
        <header class="card-head">
          <div>
            <h3>{{ c.label ?? c.name }}</h3>
            <code class="name">{{ c.name }}</code>
          </div>
          <label v-if="isAdmin" class="switch" :title="c.enabled ? 'Turn off' : 'Turn on'">
            <input type="checkbox" :checked="c.enabled" :disabled="switching === c.name" @click.prevent="toggle(c)" />
            {{ c.enabled ? "On" : "Off" }}
          </label>
          <span v-else class="badge">{{ c.enabled ? "On" : "Off" }}</span>
        </header>

        <template v-if="c.enabled">
          <p v-if="c.tools.length === 0 && c.resources.length === 0" class="muted">Nothing registered.</p>
          <ul v-if="c.tools.length" class="tools">
            <li v-for="t in c.tools" :key="t">
              <RouterLink :to="{ path: '/tools', query: { q: t } }">{{ toolTitle(t) }}</RouterLink>
              <code class="name">{{ t }}</code>
            </li>
          </ul>
          <ul v-if="resourcesOf(c).length" class="resources">
            <li v-for="r in resourcesOf(c)" :key="r.uri">
              <button type="button" class="link" @click="startRead(r)">{{ r.name }}</button>
              <code class="name">{{ r.uri }}</code>
              <span v-if="r.description" class="muted">{{ r.description }}</span>
            </li>
          </ul>
        </template>
        <p v-else class="muted">Turned off: its tools and resources aren't offered to anyone.</p>
      </article>

      <article v-if="otherResources.length" class="card">
        <header class="card-head"><h3>Other resources</h3></header>
        <ul class="resources">
          <li v-for="r in otherResources" :key="r.uri">
            <button type="button" class="link" @click="startRead(r)">{{ r.name }}</button>
            <code class="name">{{ r.uri }}</code>
          </li>
        </ul>
      </article>

      <section v-if="reading || readResult || readError" class="reader">
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
    </div>
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
h2 {
  margin: 0 0 6px;
  font-size: 1.2em;
}
h3 {
  margin: 0;
  font-size: 1em;
}
.intro {
  margin: 0 0 16px;
  font-size: 0.9em;
}
.card {
  margin-bottom: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
}
.card.off {
  opacity: 0.75;
}
.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.name {
  font-family: var(--mono);
  font-size: 0.8em;
  color: var(--muted);
  overflow-wrap: anywhere;
}
.switch {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.85em;
  cursor: pointer;
}
.badge {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 0.75em;
  color: var(--muted);
}
.tools,
.resources {
  display: grid;
  gap: 4px;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}
.tools li,
.resources li {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 10px;
  font-size: 0.9em;
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
  border-radius: 10px;
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
  border-radius: 8px;
  color: var(--text);
  background: var(--bg);
  font-family: var(--mono);
}
.primary {
  padding: 6px 16px;
  border: none;
  border-radius: 999px;
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
