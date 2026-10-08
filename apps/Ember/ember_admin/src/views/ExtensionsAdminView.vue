<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { extensionsClient, type ExtensionInfo } from "../api/ExtensionsClient";
import IntegrationToolsModal from "../components/IntegrationToolsModal.vue";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import { errorMessage } from "../utils/errors";
import "../components/infoPage.css";

const extensions = ref<ExtensionInfo[]>([]);
const query = ref("");
const filteredExtensions = computed(() => {
  const search = query.value.trim().toLowerCase();
  return extensions.value.filter((e) => `${e.id} ${e.label} ${e.description} ${e.tools.join(' ')}`.toLowerCase().includes(search));
});
const selectedId = ref<string | null>(null);
const selected = computed(() => extensions.value.find((e) => e.id === selectedId.value) ?? null);
const loading = ref(true);
const error = ref("");

const label = ref("");
const url = ref("");
const description = ref("");
const adding = ref(false);
const addError = ref("");

const removing = ref<ExtensionInfo | null>(null);
const removeBusy = ref(false);
const removeError = ref("");

async function load(): Promise<void> {
  try {
    extensions.value = await extensionsClient.list();
    error.value = "";
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

async function add(): Promise<void> {
  adding.value = true;
  addError.value = "";
  try {
    const created = await extensionsClient.add({ label: label.value, url: url.value, description: description.value });
    extensions.value = [...extensions.value, created];
    label.value = url.value = description.value = "";
  } catch (err) {
    addError.value = errorMessage(err);
  } finally {
    adding.value = false;
  }
}

async function confirmRemove(): Promise<void> {
  const target = removing.value;
  if (!target) return;
  removeBusy.value = true;
  removeError.value = "";
  try {
    await extensionsClient.remove(target.id);
    extensions.value = extensions.value.filter((e) => e.id !== target.id);
    removing.value = null;
  } catch (err) {
    removeError.value = errorMessage(err);
  } finally {
    removeBusy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="info-page extensions-admin">
    <div class="column page-column">
      <h2 class="page-title">Extensions</h2>
      <p class="intro page-description">Other MCP servers mcp_server re-exposes. An extension that is unreachable is still added; it shows its error here.</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="loading" class="muted">Loading…</p>
      <template v-else>
      <label class="page-search"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0" /></svg><input v-model="query" type="search" aria-label="Search extensions" placeholder="Search extensions or tools" /></label>
      <p class="search-count" role="status">{{ filteredExtensions.length }} of {{ extensions.length }} extensions</p>
      <p v-if="!filteredExtensions.length" class="muted">{{ extensions.length ? 'No extensions match your search.' : 'No extensions are available.' }}</p>
      <ul class="list">
        <li v-for="e in filteredExtensions" :key="e.id" class="card ext" data-test="extension" :data-id="e.id">
          <div class="top">
            <button type="button" class="who open-card" aria-haspopup="dialog" :aria-label="`Open ${e.label}`" @click="selectedId = e.id">
              <strong>{{ e.label }}</strong>
              <code>{{ e.id }}</code>
              <span class="state" :class="e.status"><span aria-hidden="true">{{ e.status === "connected" ? "●" : "○" }}</span> {{ e.status === "connected" ? "Connected" : "Error" }}</span>
            </button>
            <button type="button" class="remove" data-test="remove" @click="removing = e; removeError = ''">Remove</button>
          </div>
          <p v-if="e.description" class="muted clamp">{{ e.description }}</p>
          <p class="muted">{{ e.tools.length }} tool{{ e.tools.length === 1 ? "" : "s" }}</p>
          <p v-if="e.error" class="error clamp">{{ e.error }}</p>
        </li>
      </ul>
      </template>

      <h3>Add an extension</h3>
      <form class="add" @submit.prevent="add">
        <input v-model="label" data-test="label" type="text" placeholder="Name" aria-label="Name" required maxlength="80" autocomplete="off" />
        <input v-model="url" data-test="url" type="text" placeholder="http://host:port/mcp" aria-label="URL" required maxlength="500" autocomplete="off" />
        <input v-model="description" type="text" placeholder="What it is for (optional)" aria-label="Description" maxlength="500" autocomplete="off" />
        <button type="submit" class="primary" :disabled="adding">{{ adding ? "Adding…" : "Add" }}</button>
      </form>
      <p v-if="addError" class="error" role="alert" data-test="add-error">{{ addError }}</p>
    </div>

    <IntegrationToolsModal kind="extension" :status="selected?.status === 'connected' ? 'Connected' : 'Disconnected'" :open="selected !== null" :title="selected?.label ?? ''" :identity="selected?.id ?? ''" :names="selected?.tools ?? []" :available="selected?.status === 'connected'" @close="selectedId = null">
      <template v-if="selected"><p v-if="selected.description">{{ selected.description }}</p><p v-if="selected.error" class="error" role="alert">{{ selected.error }}</p></template>
    </IntegrationToolsModal>
    <ConfirmModal
      :open="removing !== null"
      title="Remove extension"
      :message="removeError || `Remove ${removing?.label ?? ''}? Every account that selected it loses it, and its tools disappear from mcp_server.`"
      confirm-label="Remove"
      danger
      :busy="removeBusy"
      @confirm="confirmRemove"
      @close="removing = null"
    />
  </section>
</template>

<style scoped>
.list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(260px, 100%), 1fr));
  grid-auto-rows: 1fr;
  gap: 10px;
  margin: 0 0 20px;
  padding: 0;
  list-style: none;
}
.card.ext .clamp { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; }
.card.ext { position: relative; transition: border-color 0.15s ease; }
.card.ext:hover { border-color: var(--accent); }
.open-card { border: none; padding: 0; background: transparent; color: inherit; text-align: left; cursor: pointer; font: inherit; }
.open-card::after { content: ""; position: absolute; inset: 0; border-radius: var(--radius-lg); }
.remove { position: relative; z-index: 1; }
button.open-card:focus-visible { outline: none; }
.open-card:focus-visible::after { box-shadow: inset 0 0 0 2px var(--accent); }
.who strong { flex-basis: 100%; }
@media (prefers-reduced-motion: reduce) { .card.ext { transition: none; } }
.top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.who {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.who code,
.muted {
  color: var(--muted);
}
.state {
  padding: 1px 8px;
  border-radius: var(--radius-sm);
  font-size: 0.8em;
  background: var(--surface);
}
.state.connected {
  color: var(--success);
}
.state.error {
  color: var(--danger);
}
.add {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.add input {
  flex: 1 1 200px;
  min-width: 0;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
.primary {
  padding: 6px 16px;
  border: none;
  border-radius: var(--radius-full);
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.remove {
  padding: 4px 12px;
  border: 1px solid var(--danger);
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--danger);
  font: inherit;
  cursor: pointer;
}
.error {
  color: var(--danger);
}
:is(button, input):focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>
