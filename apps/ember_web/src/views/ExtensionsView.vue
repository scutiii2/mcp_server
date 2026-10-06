<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed, onMounted, ref } from "vue";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import { extensionsClient, EXTENSION_SEPARATOR, type ExtensionInfo } from "../api/ExtensionsClient";
import AddExtensionModal from "../components/AddExtensionModal.vue";
import BaseModal from "../components/BaseModal.vue";
import "../components/infoPage.css";
import ToggleSwitch from "../components/ToggleSwitch.vue";
import { useAuthStore } from "../stores/auth";
import { useChatStore } from "../stores/chat";
import { errorMessage } from "../utils/errors";
import { safeWebUrl } from "../utils/webUrl";

/** mcp_server's extensions: other MCP servers whose tools it passes on
 * (port of chat_app's Extensions panel). Each extension is a tile with its
 * on/off switch and, for admins, Remove; a click on the tile opens its details
 * in a modal. Each user picks which ones the agent and slash commands may
 * use; admins add (modal from the button on top) and remove them. */

const auth = useAuthStore();
const chat = useChatStore();
const { enabledExtensions } = storeToRefs(chat);

const extensions = ref<ExtensionInfo[]>([]);
const loading = ref(true);
const loadError = ref("");
const actionError = ref("");
// The extension the confirm dialog asks about, and the id of the one being removed.
const pendingRemove = ref<ExtensionInfo | null>(null);
const removing = ref<string | null>(null);
const addOpen = ref(false);
const selectedId = ref<string | null>(null);

const isAdmin = computed(() => auth.hasPermission("admin.manage"));
const canChat = computed(() => auth.hasPermission("chat.use"));
// An extension's tools page runs its tools, which needs tools.use.
const canTools = computed(() => auth.hasPermission("tools.use"));

/** Where "Open page" leads: the extension's own web UI when it names a usable
 * one (a new tab), else our tools page for it (needs tools.use), else nowhere. */
function pageLink(e: ExtensionInfo): { href: string; external: boolean } | null {
  const web = safeWebUrl(e.web_url);
  if (web) return { href: web, external: true };
  return canTools.value ? { href: `/extensions/${encodeURIComponent(e.id)}`, external: false } : null;
}
const enabled = computed(() => new Set(enabledExtensions.value));
// Gone from the list (removed) closes the details with it.
const selected = computed(() => extensions.value.find((e) => e.id === selectedId.value) ?? null);

function toolName(tool: string): string {
  const at = tool.indexOf(EXTENSION_SEPARATOR);
  return at > 0 ? tool.slice(at + EXTENSION_SEPARATOR.length) : tool;
}

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    extensions.value = await extensionsClient.list();
  } catch (err) {
    loadError.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

function onAdded(created: ExtensionInfo): void {
  extensions.value = [...extensions.value.filter((e) => e.id !== created.id), created];
  addOpen.value = false;
  chat.refreshCommands();
}

const removeMessage = computed(() =>
  pendingRemove.value
    ? `Remove "${pendingRemove.value.label}"? Its tools stop being offered to every mcp_server client.`
    : "",
);

async function confirmRemove(): Promise<void> {
  const extension = pendingRemove.value;
  if (!extension) return;
  actionError.value = "";
  removing.value = extension.id;
  try {
    await extensionsClient.remove(extension.id);
    extensions.value = extensions.value.filter((e) => e.id !== extension.id);
    chat.setExtensionEnabled(extension.id, false);
    chat.refreshCommands();
  } catch (err) {
    actionError.value = errorMessage(err);
  } finally {
    removing.value = null;
    pendingRemove.value = null;
  }
}

onMounted(load);
</script>

<template>
  <section class="info-page">
    <div class="column">
      <div class="page-head">
        <h2>Extensions</h2>
        <button v-if="isAdmin" type="button" class="primary" @click="addOpen = true">Add extension</button>
      </div>
      <p class="muted intro">
        Other MCP servers mcp_server connects to. Their tools are only used in your chats when you switch them on
        here - by the agent, and as <code>/&lt;extension&gt; &lt;tool&gt;</code> commands. Click a tile for its details.
      </p>

      <p v-if="loading" class="muted">loading ...</p>
      <p v-else-if="loadError" class="error">error: {{ loadError }}</p>
      <p v-else-if="extensions.length === 0" class="muted">No extensions are configured.</p>
      <p v-if="actionError" class="error">{{ actionError }}</p>

      <div class="tiles">
        <article v-for="e in extensions" :key="e.id" class="tile">
          <button type="button" class="tile-main" @click="selectedId = e.id">
            <span class="title">
              <span :class="['dot', e.status === 'connected' ? 'ok' : 'bad']" :title="e.error ?? e.status" />
              {{ e.label }}
            </span>
            <code class="name">{{ e.id }}</code>
            <span class="summary muted">
              <template v-if="e.status !== 'connected'">Not connected</template>
              <template v-else>{{ e.tools.length }} tool{{ e.tools.length === 1 ? "" : "s" }}</template>
            </span>
          </button>
          <footer v-if="pageLink(e) || canChat || isAdmin">
            <span class="links">
              <a v-if="pageLink(e)?.external" :href="pageLink(e)!.href" target="_blank" rel="noopener noreferrer">Open page</a>
              <RouterLink v-else-if="pageLink(e)" :to="pageLink(e)!.href">Open page</RouterLink>
            </span>
            <ToggleSwitch
              v-if="canChat"
              title="Let the agent and slash commands use its tools in your chats"
              :checked="enabled.has(e.id)"
              @change="chat.setExtensionEnabled(e.id, ($event.target as HTMLInputElement).checked)"
            />
            <button v-if="isAdmin" type="button" class="danger" @click="pendingRemove = e">Remove</button>
          </footer>
        </article>
      </div>
    </div>

    <BaseModal :open="selected !== null" :title="selected?.label ?? ''" @close="selectedId = null">
      <template v-if="selected">
        <code class="name">{{ selected.id }}</code>
        <p v-if="selected.description" class="muted">{{ selected.description }}</p>
        <p v-if="selected.status !== 'connected'" class="error">
          Not connected{{ selected.error ? `: ${selected.error}` : "" }}
        </p>
        <ul v-if="selected.tools.length" class="tools">
          <li v-for="t in selected.tools" :key="t"><code>{{ toolName(t) }}</code></li>
        </ul>
        <p v-else-if="selected.status === 'connected'" class="muted">No tools.</p>
      </template>
    </BaseModal>

    <ConfirmModal
      v-if="isAdmin"
      :open="pendingRemove !== null"
      title="Remove extension"
      :message="removeMessage"
      confirm-label="Remove"
      danger
      :busy="removing !== null"
      @confirm="confirmRemove"
      @close="pendingRemove = null"
    />

    <AddExtensionModal v-if="isAdmin" :open="addOpen" @close="addOpen = false" @added="onAdded" />
  </section>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}
.page-head h2 {
  margin: 0;
}
.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}
.tile {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.tile:hover,
.tile:focus-within {
  border-color: var(--accent);
}
.tile-main {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 4px;
  padding: 14px 14px 10px;
  border: none;
  border-radius: calc(var(--radius-lg) - 1px) calc(var(--radius-lg) - 1px) 0 0;
  cursor: pointer;
  text-align: left;
  color: inherit;
  background: transparent;
  font: inherit;
}
.title {
  font-weight: 600;
}
.summary {
  margin-top: 6px;
  font-size: 0.85em;
}
.tile footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 14px 12px;
}
.links {
  display: flex;
  gap: 12px;
  font-size: 0.85em;
  white-space: nowrap;
}
.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: 4px;
  border-radius: var(--radius-full);
  vertical-align: middle;
}
.dot.ok {
  background: #2e9d5b;
}
.dot.bad {
  background: var(--danger);
}
.tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
  font-size: 0.85em;
}
</style>
