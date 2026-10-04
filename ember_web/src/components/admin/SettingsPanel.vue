<script setup lang="ts">
import { onMounted, ref } from "vue";
import { settingsClient, type AppSettings } from "../../api/SettingsClient";
import { errorMessage } from "../../utils/errors";
import "./admin.css";

const settings = ref<AppSettings | null>(null);
const loadError = ref("");
const saveError = ref("");
const saving = ref(false);

async function load(): Promise<void> {
  loadError.value = "";
  try {
    settings.value = await settingsClient.get();
  } catch (err) {
    loadError.value = errorMessage(err);
  }
}

async function setForceToolApproval(box: HTMLInputElement): Promise<void> {
  const on = box.checked;
  saveError.value = "";
  saving.value = true;
  try {
    await settingsClient.set("force_tool_approval", on);
    if (settings.value) settings.value = { ...settings.value, force_tool_approval: on };
  } catch (err) {
    saveError.value = errorMessage(err);
    // The checkbox flipped on its own; put it back to what is stored.
    box.checked = !on;
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="admin-panel">
    <h3>Tool approval</h3>
    <p v-if="loadError" class="error">error: {{ loadError }}</p>
    <label v-if="settings" class="check">
      <input
        type="checkbox"
        :checked="settings.force_tool_approval"
        :disabled="saving"
        @change="setForceToolApproval($event.target as HTMLInputElement)"
      />
      Require approval for every tool
    </label>
    <p class="muted">
      When on, every account's answers ask before each tool the agent runs, whatever the account chose, and "Allow for
      this chat" is not offered. A tool runs only after its own "Allow once". Typed commands (such as /tool) are not
      affected: the person types the exact command themselves.
    </p>
    <p v-if="saveError" class="error">{{ saveError }}</p>
  </div>
</template>
