<script setup lang="ts">
import { reactive, ref, watch } from "vue";
import { extensionsClient, type ExtensionInfo } from "../api/ExtensionsClient";
import { errorMessage } from "../utils/errors";
import BaseModal from "./BaseModal.vue";

/** The admin's "Add an extension" form in a modal. It does the add itself and
 * hands the created extension up (`added`); the parent closes it. */
const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: []; added: [extension: ExtensionInfo] }>();

const form = reactive({ label: "", url: "", description: "" });
const adding = ref(false);
const error = ref("");

// A fresh form each time it opens.
watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) return;
    form.label = form.url = form.description = "";
    error.value = "";
  },
);

async function add(): Promise<void> {
  error.value = "";
  adding.value = true;
  try {
    emit("added", await extensionsClient.add({ ...form }));
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    adding.value = false;
  }
}
</script>

<template>
  <BaseModal :open="open" title="Add an extension" @close="emit('close')">
    <form class="add" @submit.prevent="add">
      <p class="muted">
        The URL of a running MCP server (Streamable HTTP). mcp_server connects to it and offers its tools to every
        client, so only add servers you trust.
      </p>
      <label>Label <input v-model="form.label" required maxlength="80" /></label>
      <label>URL <input v-model="form.url" required type="url" maxlength="500" placeholder="http://host:port/mcp" /></label>
      <label>Description <input v-model="form.description" maxlength="500" /></label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="buttons">
        <button type="button" class="ghost" @click="emit('close')">Cancel</button>
        <button type="submit" class="primary" :disabled="adding">{{ adding ? "Adding ..." : "Add" }}</button>
      </div>
    </form>
  </BaseModal>
</template>

<style scoped>
.add {
  display: grid;
  gap: 10px;
}
.add p {
  margin: 0;
  font-size: 0.9em;
}
.add label {
  display: grid;
  gap: 4px;
  font-size: 0.85em;
  color: var(--muted);
}
.add input {
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  outline: none;
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
.add input:focus {
  border-color: var(--accent);
}
.muted {
  color: var(--muted);
}
.error {
  color: var(--danger);
}
.buttons {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.ghost,
.primary {
  padding: 5px 16px;
  border: 1px solid var(--border);
  border-radius: 999px;
  cursor: pointer;
}
.ghost {
  color: var(--muted);
  background: transparent;
}
.primary {
  border-color: var(--accent);
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.primary:disabled {
  cursor: default;
  opacity: 0.5;
}
</style>
