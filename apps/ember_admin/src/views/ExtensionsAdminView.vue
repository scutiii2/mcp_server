<script setup lang="ts">
import { onMounted, ref } from "vue";
import { extensionsClient, type ExtensionInfo } from "../api/ExtensionsClient";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import { errorMessage } from "../utils/errors";
import "../components/infoPage.css";

const extensions = ref<ExtensionInfo[]>([]);
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
    <div class="column">
      <h2>Extensions</h2>
      <p class="intro">Other MCP servers mcp_server re-exposes. An extension that is unreachable is still added; it shows its error here.</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="loading" class="muted">Loading…</p>
      <ul v-else class="list">
        <li v-for="e in extensions" :key="e.id" class="card ext" data-test="extension" :data-id="e.id">
          <div class="top">
            <div class="who">
              <strong>{{ e.label }}</strong>
              <code>{{ e.id }}</code>
              <span class="state" :class="e.status">{{ e.status === "connected" ? "Connected" : "Error" }}</span>
            </div>
            <button type="button" class="remove" data-test="remove" @click="removing = e; removeError = ''">Remove</button>
          </div>
          <p v-if="e.description" class="muted">{{ e.description }}</p>
          <p class="muted">{{ e.tools.length }} tool{{ e.tools.length === 1 ? "" : "s" }}</p>
          <p v-if="e.error" class="error">{{ e.error }}</p>
        </li>
      </ul>

      <h3>Add an extension</h3>
      <form class="add" @submit.prevent="add">
        <input v-model="label" data-test="label" type="text" placeholder="Name" aria-label="Name" required maxlength="80" autocomplete="off" />
        <input v-model="url" data-test="url" type="text" placeholder="http://host:port/mcp" aria-label="URL" required maxlength="500" autocomplete="off" />
        <input v-model="description" type="text" placeholder="What it is for (optional)" aria-label="Description" maxlength="500" autocomplete="off" />
        <button type="submit" class="primary" :disabled="adding">{{ adding ? "Adding…" : "Add" }}</button>
      </form>
      <p v-if="addError" class="error" role="alert" data-test="add-error">{{ addError }}</p>
    </div>

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
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0 0 20px;
  padding: 0;
  list-style: none;
}
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
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
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
