<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import { FOLDER_NAME_MAX, type ChatFolder } from "../api/FoldersClient";
import { useFoldersStore } from "../stores/folders";
import { errorMessage } from "../utils/errors";
import BaseModal from "./BaseModal.vue";

// The folder dialogs of the chat page (new, rename, delete), driven from the
// outside through the exposed open* methods. One dialog at a time. Every
// failure ember_api reports (a duplicate name, the folder limit, a chat that is
// still answering) is shown inside the dialog, which stays open.
type Mode =
  | { kind: "create"; onCreated?: (folder: ChatFolder) => void }
  | { kind: "rename"; folder: ChatFolder }
  | { kind: "delete"; folder: ChatFolder; chatCount: number };

const store = useFoldersStore();

const mode = ref<Mode | null>(null);
const name = ref("");
const error = ref("");
const busy = ref(false);
const nameInput = ref<HTMLInputElement | null>(null);

const title = computed(() => {
  switch (mode.value?.kind) {
    case "create":
      return "New folder";
    case "rename":
      return "Rename folder";
    case "delete":
      return "Delete folder";
    default:
      return "";
  }
});
const canSave = computed(() => name.value.trim() !== "" && !busy.value);
const deleteText = computed(() => {
  const m = mode.value;
  if (m?.kind !== "delete") return "";
  return `Delete folder "${m.folder.name}" and its ${m.chatCount} ${m.chatCount === 1 ? "chat" : "chats"}? This can't be undone.`;
});

function begin(next: Mode, initialName = ""): void {
  mode.value = next;
  name.value = initialName;
  error.value = "";
  busy.value = false;
  // BaseModal opens its <dialog> one tick after `open` flips, so wait for it.
  void nextTick().then(nextTick).then(() => nameInput.value?.focus());
}

function openCreate(onCreated?: (folder: ChatFolder) => void): void {
  begin({ kind: "create", onCreated });
}
function openRename(folder: ChatFolder): void {
  begin({ kind: "rename", folder }, folder.name);
}
function openDelete(folder: ChatFolder, chatCount: number): void {
  begin({ kind: "delete", folder, chatCount });
}
defineExpose({ openCreate, openRename, openDelete });

/** Close requested by the user (Esc, backdrop, x, Cancel). Ignored while a
 * request is in flight so its outcome is never lost or applied to a later dialog. */
function requestClose(): void {
  if (!busy.value) mode.value = null;
}
function dismiss(): void {
  mode.value = null;
}

async function save(): Promise<void> {
  const m = mode.value;
  if (!m || m.kind === "delete" || !canSave.value) return;
  const trimmed = name.value.replace(/\s+/g, " ").trim();
  busy.value = true;
  error.value = "";
  try {
    if (m.kind === "create") {
      const folder = await store.create(trimmed);
      dismiss();
      m.onCreated?.(folder);
    } else {
      if (trimmed !== m.folder.name) await store.rename(m.folder.id, trimmed);
      dismiss();
    }
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    busy.value = false;
  }
}

async function confirmDelete(): Promise<void> {
  const m = mode.value;
  if (m?.kind !== "delete" || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await store.remove(m.folder.id);
    dismiss();
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <BaseModal :open="mode !== null" :title="title" @close="requestClose">
    <form v-if="mode && mode.kind !== 'delete'" class="form" @submit.prevent="save">
      <label>
        Name
        <input ref="nameInput" v-model="name" type="text" :maxlength="FOLDER_NAME_MAX" autocomplete="off" />
      </label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="buttons">
        <button type="button" class="ghost" @click="requestClose">Cancel</button>
        <button type="submit" class="primary" :disabled="!canSave">{{ busy ? "Saving …" : "Save" }}</button>
      </div>
    </form>
    <div v-else-if="mode" class="form">
      <p class="confirm">{{ deleteText }}</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="buttons">
        <button type="button" class="ghost" @click="requestClose">Cancel</button>
        <button type="button" class="danger" :disabled="busy" @click="confirmDelete">{{ busy ? "Deleting …" : "Delete" }}</button>
      </div>
    </div>
  </BaseModal>
</template>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.9em;
  color: var(--muted);
}
input[type="text"] {
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  outline: none;
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
input[type="text"]:focus {
  border-color: var(--accent);
}
.confirm {
  margin: 0;
}
.error {
  margin: 0;
  color: var(--danger);
  font-size: 0.9em;
}
.buttons {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
button {
  padding: 7px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
button:disabled {
  cursor: default;
  opacity: 0.5;
}
.primary {
  border-color: var(--accent);
  color: var(--accent-contrast);
  background: var(--accent);
}
.danger {
  border-color: var(--danger);
  color: var(--danger);
}
.ghost {
  background: transparent;
}
</style>
