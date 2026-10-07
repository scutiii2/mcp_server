<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { settingsClient, type AppSettings } from "../../api/SettingsClient";
import { errorMessage } from "../../utils/errors";
import LockSwitch from "../LockSwitch.vue";
import "./admin.css";

/** Whether the stored value differs from the default (off), for a page that counts changed settings. */
const emit = defineEmits<{ modified: [value: boolean] }>();

const settings = ref<AppSettings | null>(null);
const loadError = ref("");
const saveError = ref("");
const saving = ref(false);
const saved = ref(false);

// This setting reaches every account, so a flip is only a draft until Save: the
// bar shows what will change and who it applies to, and Cancel drops it.
const draft = ref(false);
const dirty = computed(() => settings.value !== null && draft.value !== settings.value.force_tool_approval);

async function load(): Promise<void> {
  loadError.value = "";
  try {
    settings.value = await settingsClient.get();
    draft.value = settings.value.force_tool_approval;
  } catch (err) {
    loadError.value = errorMessage(err);
  }
}

function setDraft(box: HTMLInputElement): void {
  draft.value = box.checked;
  saved.value = false;
  saveError.value = "";
}

// The stored value is what counts as changed; a draft only becomes one once saved.
const storedOn = computed(() => settings.value?.force_tool_approval === true);
watch(storedOn, (on) => emit("modified", on), { immediate: true });

/** Puts the switch back to the default (off). Like any flip it is a draft until Save. */
function resetToDefault(): void {
  draft.value = false;
  saved.value = false;
  saveError.value = "";
}

function cancel(): void {
  draft.value = settings.value?.force_tool_approval ?? false;
  saveError.value = "";
}

async function save(): Promise<void> {
  const on = draft.value;
  saveError.value = "";
  saving.value = true;
  try {
    await settingsClient.set("force_tool_approval", on);
    if (settings.value) settings.value = { ...settings.value, force_tool_approval: on };
    saved.value = true;
  } catch (err) {
    // The draft stays, so Save can be retried or Cancel drops it.
    saveError.value = errorMessage(err);
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="admin-panel">
    <p v-if="loadError" class="error">error: {{ loadError }}</p>
    <section class="card">
      <div class="head">
        <span v-if="storedOn" class="dot" title="Changed from the default" aria-hidden="true" />
        <h3>Tool approval</h3>
        <button v-if="draft" type="button" class="small" :disabled="saving" @click="resetToDefault">Back to default</button>
        <span v-if="saved && !dirty" class="chip saved">Saved</span>
        <span class="chip scope">Applies to all accounts</span>
      </div>
      <LockSwitch
        v-if="settings"
        :checked="draft"
        :disabled="saving"
        @change="setDraft($event.target as HTMLInputElement)"
      >
        Require approval for every tool
      </LockSwitch>
      <p class="muted">
        When on, every account's answers ask before each tool the agent runs, whatever the account chose, and "Allow
        for this chat" is not offered. A tool runs only after its own "Allow once". Typed commands (such as /tool) are
        not affected: the person types the exact command themselves.
      </p>
      <div v-if="dirty" class="save-bar" role="group" aria-label="Unsaved change">
        <span class="dot" aria-hidden="true" />
        <span class="msg">
          You have an unsaved change. Turning it {{ draft ? "on" : "off" }} applies to every account.
        </span>
        <button type="button" class="small" :disabled="saving" @click="cancel">Cancel</button>
        <button type="button" class="primary" :disabled="saving" @click="save">Save</button>
      </div>
      <p v-if="saveError" class="error">{{ saveError }}</p>
    </section>
  </div>
</template>

<style scoped>
.card h3 {
  margin: 0;
}
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.chip.scope {
  margin-left: auto;
}
.chip.saved {
  color: var(--success);
  border-color: var(--success);
}
.save-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg);
}
.save-bar .msg {
  flex: 1 1 200px;
  font-size: 0.9em;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--accent);
}
.card p {
  margin-bottom: 0;
}
</style>
