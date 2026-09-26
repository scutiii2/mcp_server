<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed, onMounted, reactive, ref } from "vue";
import { extensionsClient, EXTENSION_SEPARATOR, type ExtensionInfo } from "../api/ExtensionsClient";
import "../components/infoPage.css";
import { useAuthStore } from "../stores/auth";
import { useChatStore } from "../stores/chat";
import { errorMessage } from "../utils/errors";

/** mcp_server's extensions: other MCP servers whose tools it passes on
 * (port of chat_app's Extensions panel). Each user picks which ones the
 * agent and slash commands may use; admins add and remove them. */

const auth = useAuthStore();
const chat = useChatStore();
const { enabledExtensions } = storeToRefs(chat);

const extensions = ref<ExtensionInfo[]>([]);
const loading = ref(true);
const loadError = ref("");
const actionError = ref("");
const removing = ref<string | null>(null);
const adding = ref(false);
const form = reactive({ label: "", url: "", description: "" });

const isAdmin = computed(() => auth.hasPermission("admin.manage"));
const canChat = computed(() => auth.hasPermission("chat.use"));
const enabled = computed(() => new Set(enabledExtensions.value));

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

async function add(): Promise<void> {
  actionError.value = "";
  adding.value = true;
  try {
    const created = await extensionsClient.add({ ...form });
    extensions.value = [...extensions.value.filter((e) => e.id !== created.id), created];
    form.label = form.url = form.description = "";
    chat.refreshCommands();
  } catch (err) {
    actionError.value = errorMessage(err);
  } finally {
    adding.value = false;
  }
}

async function remove(extension: ExtensionInfo): Promise<void> {
  if (!confirm(`Remove "${extension.label}"? Its tools stop being offered to every mcp_server client.`)) return;
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
  }
}

onMounted(load);
</script>

<template>
  <section class="info-page">
    <div class="column">
      <h2>Extensions</h2>
      <p class="muted intro">
        Other MCP servers mcp_server connects to. Their tools are only used in your chats when you switch them on
        here - by the agent, and as <code>/&lt;extension&gt; &lt;tool&gt;</code> commands.
      </p>

      <p v-if="loading" class="muted">loading ...</p>
      <p v-else-if="loadError" class="error">error: {{ loadError }}</p>
      <p v-else-if="extensions.length === 0" class="muted">No extensions are configured.</p>
      <p v-if="actionError" class="error">{{ actionError }}</p>

      <article v-for="e in extensions" :key="e.id" class="card">
        <header class="card-head">
          <div>
            <h3>
              <span :class="['dot', e.status === 'connected' ? 'ok' : 'bad']" :title="e.error ?? e.status" />
              {{ e.label }}
            </h3>
            <code class="name">{{ e.id }}</code>
          </div>
          <div class="actions">
            <label v-if="canChat" class="switch" title="Let the agent and slash commands use its tools in your chats">
              <input
                type="checkbox"
                :checked="enabled.has(e.id)"
                @change="chat.setExtensionEnabled(e.id, ($event.target as HTMLInputElement).checked)"
              />
              Use in my chats
            </label>
            <button v-if="isAdmin" type="button" class="danger" :disabled="removing === e.id" @click="remove(e)">
              Remove
            </button>
          </div>
        </header>
        <p v-if="e.description" class="muted">{{ e.description }}</p>
        <p v-if="e.status !== 'connected'" class="error">Not connected{{ e.error ? `: ${e.error}` : "" }}</p>
        <ul v-if="e.tools.length" class="tools">
          <li v-for="t in e.tools" :key="t"><code>{{ toolName(t) }}</code></li>
        </ul>
        <p v-else-if="e.status === 'connected'" class="muted">No tools.</p>
      </article>

      <form v-if="isAdmin" class="card add" @submit.prevent="add">
        <h3>Add an extension</h3>
        <p class="muted">
          The URL of a running MCP server (Streamable HTTP). mcp_server connects to it and offers its tools to every
          client, so only add servers you trust.
        </p>
        <label>Label <input v-model="form.label" required maxlength="80" /></label>
        <label>URL <input v-model="form.url" required type="url" maxlength="500" placeholder="http://host:port/mcp" /></label>
        <label>Description <input v-model="form.description" maxlength="500" /></label>
        <button class="primary" :disabled="adding">{{ adding ? "Adding ..." : "Add" }}</button>
      </form>
    </div>
  </section>
</template>

<style scoped>
.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: 4px;
  border-radius: 50%;
  vertical-align: middle;
}
.dot.ok {
  background: #2e9d5b;
}
.dot.bad {
  background: var(--danger);
}
.actions {
  display: flex;
  align-items: center;
  gap: 10px;
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
.add {
  display: grid;
  gap: 8px;
}
.add label {
  display: grid;
  gap: 4px;
  font-size: 0.85em;
}
.add .primary {
  justify-self: start;
}
</style>
