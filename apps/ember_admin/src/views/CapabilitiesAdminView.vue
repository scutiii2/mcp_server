<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { capabilitiesAdminClient, type CapabilityStatus } from "../api/CapabilitiesAdminClient";
import { commandsClient } from "../api/CommandsClient";
import IntegrationToolsModal from "../components/IntegrationToolsModal.vue";
import ToggleSwitch from "../components/ToggleSwitch.vue";
import { errorMessage } from "../utils/errors";
import "../components/infoPage.css";

const capabilities = ref<CapabilityStatus[]>([]);
const query = ref("");
const selectedName = ref<string | null>(null);
const selected = computed(() => capabilities.value.find((c) => c.name === selectedName.value) ?? null);
const summaries = ref<Record<string, string>>({});
let summariesRequest: Promise<void> | null = null;
watch(selectedName, (name) => {
  if (!name || summariesRequest) return;
  summariesRequest = commandsClient.helpIndex().then((index) => {
    if (!index || typeof index !== "object" || !("capabilities" in index) || !Array.isArray(index.capabilities)) return;
    for (const row of index.capabilities) {
      if (row && typeof row.capability === "string" && typeof row.summary === "string" && row.summary.trim()) {
        summaries.value[row.capability.replace(/^\//, "")] = row.summary.trim();
      }
    }
  }).catch(() => { /* The fallback remains visible if help metadata is unavailable. */ })
    .finally(() => { summariesRequest = null; });
});
const loading = ref(true);
const error = ref("");
const refreshing = ref(false);
// A switch waits for the server's answer: the name is here while its call is in flight.
const pending = ref<Set<string>>(new Set());
const rowErrors = ref<Record<string, string>>({});

type State = "online" | "offline" | "new" | "error" | "missing";

function stateOf(c: CapabilityStatus): State {
  if (c.missing) return "missing";
  if (c.enabled) return "online";
  if (c.load_error) return "error";
  if (!c.loaded) return "new";
  return "offline";
}

const STATE_LABELS: Record<State, string> = {
  online: "Online",
  offline: "Offline",
  new: "New, offline",
  error: "Failed to load",
  missing: "Folder missing",
};

const rows = computed(() => {
  const search = query.value.trim().toLowerCase();
  return capabilities.value.filter((c) => `${c.name} ${c.label ?? ''} ${c.tools.join(' ')}`.toLowerCase().includes(search))
    .map((c) => ({ c, state: stateOf(c) }));
});

async function load(): Promise<void> {
  try {
    capabilities.value = await capabilitiesAdminClient.list();
    error.value = "";
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

async function refresh(): Promise<void> {
  refreshing.value = true;
  try {
    capabilities.value = await capabilitiesAdminClient.refresh();
    error.value = "";
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    refreshing.value = false;
  }
}

async function setOnline(c: CapabilityStatus, online: boolean): Promise<void> {
  pending.value = new Set(pending.value).add(c.name);
  delete rowErrors.value[c.name];
  try {
    const updated = await capabilitiesAdminClient.setOnline(c.name, online);
    capabilities.value = capabilities.value.map((x) => (x.name === c.name ? updated : x));
  } catch (err) {
    rowErrors.value[c.name] = errorMessage(err);
    // The server rolled back; read the real state (and its load_error) again.
    await load();
  } finally {
    const next = new Set(pending.value);
    next.delete(c.name);
    pending.value = next;
  }
}

// The checkbox flips natively on click; put it back so only the server's answer moves it.
function onToggle(c: CapabilityStatus, event: Event): void {
  const input = event.target as HTMLInputElement;
  const wanted = input.checked;
  input.checked = c.enabled;
  void setOnline(c, wanted);
}

onMounted(load);
</script>

<template>
  <section class="info-page capabilities-admin">
    <div class="column page-column">
      <header class="head">
        <div>
          <h2 class="page-title">Capabilities</h2>
          <p class="intro page-description">
            Offline hides a capability's tools from every client. Going online loads its code from disk again, so edit
            while it is offline. Refresh finds capability folders added while mcp_server runs; they start offline.
          </p>
        </div>
        <button type="button" class="refresh" data-test="refresh" :disabled="refreshing" @click="refresh">
          {{ refreshing ? "Refreshing…" : "Refresh" }}
        </button>
      </header>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="loading" class="muted">Loading…</p>
      <template v-else>
      <label class="page-search"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0" /></svg><input v-model="query" type="search" aria-label="Search capabilities" placeholder="Search capabilities or tools" /></label>
      <p class="search-count" role="status">{{ rows.length }} of {{ capabilities.length }} capabilities</p>
      <p v-if="!rows.length" class="muted">{{ capabilities.length ? 'No capabilities match your search.' : 'No capabilities are available.' }}</p>
      <ul class="list">
        <li v-for="{ c, state } in rows" :key="c.name" class="card cap" data-test="capability" :data-name="c.name" :data-state="state">
          <div class="top">
            <button type="button" class="who open-card" aria-haspopup="dialog" :aria-label="`Open ${c.label ?? c.name}`" @click="selectedName = c.name">
              <strong>{{ c.label ?? c.name }}</strong>
              <code>{{ c.name }}</code>
              <span class="state" :class="state"><span aria-hidden="true">{{ state === 'online' ? '●' : '○' }}</span> {{ STATE_LABELS[state] }}</span>
            </button>
            <ToggleSwitch
              :checked="c.enabled"
              :disabled="pending.has(c.name) || (c.missing && !c.enabled)"
              :aria-label="`${c.label ?? c.name} online`"
              @change="onToggle(c, $event)"
            />
          </div>
          <p class="tools">{{ c.tools.length }} tool{{ c.tools.length === 1 ? "" : "s" }}<template v-if="!c.loaded"> · not loaded yet</template></p>
          <pre v-if="c.load_error" class="load-error" data-test="load-error">{{ c.load_error }}</pre>
          <p v-if="rowErrors[c.name]" class="error" role="alert" data-test="row-error">{{ rowErrors[c.name] }}</p>
        </li>
      </ul>
      </template>
    </div>
    <IntegrationToolsModal kind="capability" :status="selected ? STATE_LABELS[stateOf(selected)] : ''" :open="selected !== null" :title="selected?.label ?? selected?.name ?? ''" :identity="selected?.name ?? ''" :names="selected?.tools ?? []" :available="selected?.enabled ?? false" @close="selectedName = null">
      <template v-if="selected"><p>{{ summaries[selected.name] ?? `Workspace tools provided by ${selected.label ?? selected.name}. Select a tool below to explore what it does.` }}</p><pre v-if="selected.load_error" class="load-error">{{ selected.load_error }}</pre></template>
    </IntegrationToolsModal>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}
.refresh {
  padding: 6px 16px;
  border: none;
  border-radius: var(--radius-full);
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.refresh:disabled {
  opacity: 0.6;
  cursor: default;
}
.list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(260px, 100%), 1fr));
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.card.cap { position: relative; transition: border-color 0.15s ease; }
.card.cap:hover { border-color: var(--accent); }
.open-card { border: none; padding: 0; background: transparent; color: inherit; text-align: left; cursor: pointer; font: inherit; }
.open-card::after { content: ""; position: absolute; inset: 0; border-radius: var(--radius-lg); }
.top :deep(.toggle) { position: relative; z-index: 1; flex-shrink: 0; }
button.open-card:focus-visible { outline: none; }
.open-card:focus-visible::after { box-shadow: inset 0 0 0 2px var(--accent); }
.who strong { flex-basis: 100%; }
@media (prefers-reduced-motion: reduce) { .card.cap { transition: none; } }
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
.who code {
  color: var(--muted);
}
.state {
  padding: 1px 8px;
  border-radius: var(--radius-sm);
  font-size: 0.8em;
  background: var(--surface);
}
.state.online {
  color: var(--success);
}
.state.error,
.state.missing {
  color: var(--danger);
}
.tools {
  margin: 6px 0 0;
  font-size: 0.9em;
  color: var(--muted);
}
.load-error {
  margin: 8px 0 0;
  padding: 8px 10px;
  max-height: 220px;
  overflow: auto;
  border-radius: var(--radius-md);
  background: var(--code-bg);
  font: 0.8em/1.4 var(--mono);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.error {
  color: var(--danger);
}
.muted {
  color: var(--muted);
}
</style>
