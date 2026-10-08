<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { capabilitiesAdminClient, type CapabilityStatus } from "../api/CapabilitiesAdminClient";
import ToggleSwitch from "../components/ToggleSwitch.vue";
import { errorMessage } from "../utils/errors";
import "../components/infoPage.css";

const capabilities = ref<CapabilityStatus[]>([]);
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

const rows = computed(() => capabilities.value.map((c) => ({ c, state: stateOf(c) })));

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
    <div class="column">
      <header class="head">
        <div>
          <h2>Capabilities</h2>
          <p class="intro">
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
      <ul v-else class="list">
        <li v-for="{ c, state } in rows" :key="c.name" class="card cap" data-test="capability" :data-name="c.name" :data-state="state">
          <div class="top">
            <div class="who">
              <strong>{{ c.label ?? c.name }}</strong>
              <code>{{ c.name }}</code>
              <span class="state" :class="state">{{ STATE_LABELS[state] }}</span>
            </div>
            <ToggleSwitch
              :checked="c.enabled"
              :disabled="pending.has(c.name) || c.missing"
              :aria-label="`${c.label ?? c.name} online`"
              @change="onToggle(c, $event)"
            />
          </div>
          <p class="tools">{{ c.tools.length }} tool{{ c.tools.length === 1 ? "" : "s" }}<template v-if="!c.loaded"> · not loaded yet</template></p>
          <pre v-if="c.load_error" class="load-error" data-test="load-error">{{ c.load_error }}</pre>
          <p v-if="rowErrors[c.name]" class="error" role="alert" data-test="row-error">{{ rowErrors[c.name] }}</p>
        </li>
      </ul>
    </div>
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
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0;
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
