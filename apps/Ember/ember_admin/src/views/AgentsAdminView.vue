<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  agentsAdminClient,
  type AgentConfig,
  type AgentFile,
  type LiveAgent,
  type ProviderCatalog,
} from "../api/AgentsAdminClient";
import AgentAdminCard from "../components/admin/AgentAdminCard.vue";
import AgentForm from "../components/admin/AgentForm.vue";
import SharedPromptsModal from "../components/admin/SharedPromptsModal.vue";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import { errorMessage } from "../utils/errors";
import "../components/infoPage.css";

// ai_agent's supervisor rescans its agents folder about every 2 seconds.
const SETTLE_MS = 3000;

const agents = ref<AgentFile[]>([]);
const providers = ref<ProviderCatalog>({});
const live = ref<Record<string, LiveAgent>>({});
const loading = ref(true);
const error = ref("");
const notice = ref("");

const formOpen = ref(false);
const editing = ref<AgentFile | null>(null);
const saving = ref(false);
const formError = ref("");

const previewText = ref("");
const previewing = ref(false);
const previewError = ref("");
const promptsOpen = ref(false);

const removing = ref<AgentFile | null>(null);
const removeBusy = ref(false);
const removeError = ref("");

let settleTimer: ReturnType<typeof setTimeout> | undefined;

const suggestedPort = computed(() => Math.max(9100, ...agents.value.map((a) => a.port ?? 0)) + 1);

async function loadStatuses(): Promise<void> {
  try {
    live.value = await agentsAdminClient.live();
  } catch {
    live.value = {}; // needs chat.use; without it the status and tiers are simply left out
  }
}

async function load(): Promise<void> {
  try {
    const [files, catalog] = await Promise.all([agentsAdminClient.list(), agentsAdminClient.gateways()]);
    agents.value = files;
    providers.value = catalog;
    error.value = "";
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
  await loadStatuses();
}

function settleSoon(message: string): void {
  notice.value = message;
  clearTimeout(settleTimer);
  settleTimer = setTimeout(() => {
    void loadStatuses();
    notice.value = "";
  }, SETTLE_MS);
}

async function preview(id: string, config: AgentConfig, caveman: boolean): Promise<void> {
  previewing.value = true;
  previewError.value = "";
  try {
    previewText.value = await agentsAdminClient.previewPrompt(id, config, caveman);
  } catch (err) {
    previewText.value = "";
    previewError.value = errorMessage(err);
  } finally {
    previewing.value = false;
  }
}

function resetPreview(): void {
  previewText.value = "";
  previewError.value = "";
}

function openCreate(): void {
  resetPreview();
  editing.value = null;
  formError.value = "";
  formOpen.value = true;
}

function openEdit(agent: AgentFile): void {
  resetPreview();
  editing.value = agent;
  formError.value = "";
  formOpen.value = true;
}

async function save(id: string, config: AgentConfig): Promise<void> {
  saving.value = true;
  formError.value = "";
  const creating = editing.value === null;
  try {
    if (creating) await agentsAdminClient.create(id, config);
    else await agentsAdminClient.update(id, config);
    formOpen.value = false;
    agents.value = await agentsAdminClient.list();
    settleSoon(creating ? `Created ${id}. It starts in a few seconds.` : `Saved ${id}. It restarts in a few seconds.`);
  } catch (err) {
    formError.value = errorMessage(err);
  } finally {
    saving.value = false;
  }
}

async function confirmRemove(): Promise<void> {
  const target = removing.value;
  if (!target) return;
  removeBusy.value = true;
  removeError.value = "";
  try {
    await agentsAdminClient.remove(target.id);
    agents.value = agents.value.filter((a) => a.id !== target.id);
    removing.value = null;
    settleSoon(`Removed ${target.id}. It stops in a few seconds.`);
  } catch (err) {
    removeError.value = errorMessage(err);
  } finally {
    removeBusy.value = false;
  }
}

onMounted(load);
onBeforeUnmount(() => clearTimeout(settleTimer));
</script>

<template>
  <section class="info-page agents-admin">
    <div class="column page-column">
      <div class="head">
        <div>
          <h2 class="page-title">Agents</h2>
          <p class="intro page-description">Each agent is a file ai_agent runs as its own process. Changes apply within a few seconds, no restart.</p>
        </div>
        <div class="head-actions">
          <button type="button" class="chip" data-test="shared-prompts" @click="promptsOpen = true">Shared prompts</button>
          <button type="button" class="primary" data-test="new" @click="openCreate">＋ New agent</button>
        </div>
      </div>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="notice" class="notice" role="status" data-test="notice">{{ notice }}</p>
      <p v-if="loading" class="muted">Loading…</p>
      <p v-else-if="!agents.length && !error" class="muted">No agents are defined.</p>
      <div class="grid">
        <AgentAdminCard
          v-for="a in agents"
          :key="a.id"
          :agent="a"
          :status="live[a.id]?.status"
          :tiers="live[a.id]?.tiers"
          @edit="openEdit(a)"
          @remove="removing = a; removeError = ''"
        />
      </div>
    </div>

    <AgentForm
      :open="formOpen"
      :initial="editing"
      :providers="providers"
      :suggested-port="suggestedPort"
      :busy="saving"
      :error="formError"
      :preview-text="previewText"
      :previewing="previewing"
      :preview-error="previewError"
      @save="save"
      @preview="preview"
      @close="formOpen = false"
    />
    <SharedPromptsModal :open="promptsOpen" @close="promptsOpen = false" @saved="settleSoon('Shared prompts saved. Every agent restarts in a few seconds.')" />
    <ConfirmModal
      :open="removing !== null"
      title="Remove agent"
      :message="removeError || `Remove ${removing?.label || removing?.id || ''}? Its file is deleted and the agent stops. Other agents that delegate to it will find it gone.`"
      confirm-label="Remove"
      danger
      :require-text="removing?.id ?? ''"
      :busy="removeBusy"
      @confirm="confirmRemove"
      @close="removing = null"
    />
  </section>
</template>

<style scoped>
.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  grid-auto-rows: 1fr;
  gap: 12px;
  margin: 0 0 20px;
}
.head-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.chip { padding: 6px 14px; border: 1px solid var(--border); border-radius: var(--radius-full); background: transparent; color: var(--text); font: inherit; cursor: pointer; }
.muted { color: var(--muted); }
.primary { flex-shrink: 0; padding: 6px 16px; border: none; border-radius: var(--radius-full); cursor: pointer; font: inherit; font-weight: 600; color: var(--accent-contrast); background: var(--accent); }
.error { color: var(--danger); }
.notice { color: var(--muted); }
:is(button, input):focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
</style>
