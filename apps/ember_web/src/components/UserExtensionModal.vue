<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import type { UserExtension } from "../api/UserExtensionsClient";
import { useUserExtensionsStore } from "../stores/userExtensions";
import { errorMessage } from "../utils/errors";
import BaseModal from "./BaseModal.vue";

/** Adds a private extension (`extension` null) or edits one. Saved headers are
 * secrets ember_api never sends back, so an edit lists their names only and
 * keeps them unless the user opens "Replace headers": then what is typed
 * becomes the whole set (none removes them all). Value inputs are masked. The
 * server's message for a refused address or header is shown here. */
const props = defineProps<{ open: boolean; extension: UserExtension | null }>();
const emit = defineEmits<{ close: []; saved: [extension: UserExtension] }>();

const store = useUserExtensionsStore();

const form = reactive({ label: "", url: "", description: "" });
const rows = ref<{ name: string; value: string }[]>([]);
// Editing: the saved headers are being replaced by the rows below.
const replacing = ref(false);
const saving = ref(false);
const error = ref("");

const editing = computed(() => props.extension !== null);
const showEditor = computed(() => !editing.value || replacing.value);

function hostOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

// An edit that moves the address to another host drops the saved headers (ember_api does that
// so a token is never sent to a host the user did not give it to).
const hostWarning = computed(
  () =>
    props.extension !== null &&
    !replacing.value &&
    props.extension.header_names.length > 0 &&
    hostOf(form.url) !== "" &&
    hostOf(form.url) !== hostOf(props.extension.url),
);

// A fresh form each time it opens.
watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) return;
    form.label = props.extension?.label ?? "";
    form.url = props.extension?.url ?? "";
    form.description = props.extension?.description ?? "";
    rows.value = [];
    replacing.value = false;
    error.value = "";
  },
  { immediate: true },
);

function addRow(): void {
  rows.value.push({ name: "", value: "" });
}

function startReplacing(): void {
  replacing.value = true;
  rows.value = [];
}

function typedHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const row of rows.value) {
    if (row.name.trim() === "" && row.value === "") continue;
    headers[row.name.trim()] = row.value;
  }
  return headers;
}

async function save(): Promise<void> {
  error.value = "";
  saving.value = true;
  try {
    const base = { label: form.label, url: form.url, description: form.description };
    const headers = showEditor.value ? typedHeaders() : null;
    const saved = props.extension
      ? await store.update(props.extension.id, headers ? { ...base, headers } : base)
      : await store.add(headers && Object.keys(headers).length > 0 ? { ...base, headers } : base);
    emit("saved", saved);
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <BaseModal :open="open" :title="editing ? 'Edit private extension' : 'Add your own extension'" @close="emit('close')">
    <form class="form" @submit.prevent="save">
      <p class="muted">
        The address of an MCP server you run or trust (Streamable HTTP). Only you can see it and only your chats use it.
        Its tools always ask before they run.
      </p>
      <label>Label <input v-model="form.label" name="label" required maxlength="60" /></label>
      <label>
        Address
        <input v-model="form.url" name="url" required type="url" maxlength="1000" placeholder="https://host/mcp" />
      </label>
      <label>Description <input v-model="form.description" name="description" maxlength="300" /></label>

      <fieldset class="headers">
        <legend>Headers</legend>
        <template v-if="editing && !replacing">
          <p class="saved-headers muted">
            <template v-if="extension!.header_names.length">Saved headers: {{ extension!.header_names.join(", ") }}</template>
            <template v-else>No headers saved.</template>
            Their values are never shown.
          </p>
          <button type="button" class="ghost replace-headers" @click="startReplacing">Replace headers</button>
        </template>
        <template v-else>
          <p v-if="editing" class="muted">These replace every saved header. Leave none to remove them all.</p>
          <p v-else class="muted">Optional: for a server that wants a token or key.</p>
          <div v-for="(row, index) in rows" :key="index" class="row">
            <input
              v-model="row.name"
              class="header-name"
              :aria-label="`Header name ${index + 1}`"
              placeholder="X-Api-Key"
              maxlength="64"
              autocomplete="off"
              spellcheck="false"
            />
            <input
              v-model="row.value"
              class="header-value"
              type="password"
              :aria-label="`Header value ${index + 1}`"
              placeholder="value"
              maxlength="2000"
              autocomplete="off"
            />
            <button type="button" class="remove-header" :aria-label="`Remove header ${index + 1}`" @click="rows.splice(index, 1)">
              &times;
            </button>
          </div>
          <button type="button" class="ghost add-header" :disabled="rows.length >= 20" @click="addRow">Add header</button>
        </template>
        <p v-if="hostWarning" class="host-warning">
          The address is on another host, so the saved headers will be removed. Use Replace headers to set new ones.
        </p>
      </fieldset>

      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="buttons">
        <button type="button" class="ghost" @click="emit('close')">Cancel</button>
        <button type="submit" class="primary" :disabled="saving">{{ saving ? "Saving ..." : editing ? "Save" : "Add" }}</button>
      </div>
    </form>
  </BaseModal>
</template>

<style scoped>
.form {
  display: grid;
  gap: 10px;
}
.form p {
  margin: 0;
  font-size: 0.9em;
}
.form label {
  display: grid;
  gap: 4px;
  font-size: 0.85em;
  color: var(--muted);
}
input {
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  outline: none;
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
input:focus {
  border-color: var(--accent);
}
.headers {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.headers legend {
  padding: 0 6px;
  font-size: 0.85em;
  color: var(--muted);
}
.row {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 6px;
}
.muted {
  color: var(--muted);
}
.error,
.host-warning {
  color: var(--danger);
}
.buttons {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.ghost,
.primary,
.remove-header {
  padding: 5px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  cursor: pointer;
}
.ghost,
.remove-header {
  color: var(--muted);
  background: transparent;
}
.ghost {
  justify-self: start;
}
.remove-header {
  padding: 5px 12px;
}
.primary {
  border-color: var(--accent);
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.primary:disabled,
.ghost:disabled {
  cursor: default;
  opacity: 0.5;
}
button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>
