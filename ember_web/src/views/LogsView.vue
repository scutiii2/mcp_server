<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { logsClient, type LogActor, type LogEntry, type LogKind } from "../api/LogsClient";
import "../components/infoPage.css";
import { useAuthStore } from "../stores/auth";
import { errorMessage } from "../utils/errors";

/** Activity, error and chat-turn logs (port of chat_app's Logs page). Each
 * tab needs its own permission; each shows one actor at a time - the
 * server or one account - newest first, the latest 200. */

const TAB_LABELS: Record<LogKind, string> = { action: "Activity", error: "Errors", chat_trace: "Chat turns" };

const auth = useAuthStore();
const kinds = ref<LogKind[]>([]);
const accounts = ref<{ id: number; username: string }[]>([]);
const tab = ref<LogKind | null>(null);
// Per tab, like chat_app. Errors and chat turns start on the viewer's own
// account: a chat turn always belongs to one, and most errors do too.
const actors = ref<Record<LogKind, LogActor>>({ action: "server", error: "server", chat_trace: "server" });
const entries = ref<LogEntry[]>([]);
const loading = ref(false);
const error = ref("");

const actorOptions = computed(() => [
  ...(tab.value === "chat_trace" ? [] : [{ value: "server" as LogActor, label: "Server" }]),
  ...accounts.value.map((a) => ({ value: a.id as LogActor, label: a.username })),
]);

function time(iso: string): string {
  return new Date(`${iso}Z`).toLocaleString();
}

async function loadEntries(): Promise<void> {
  const kind = tab.value;
  if (!kind) return;
  loading.value = true;
  error.value = "";
  try {
    const result = await logsClient.list(kind, actors.value[kind]);
    if (tab.value === kind) entries.value = result;
  } catch (err) {
    error.value = errorMessage(err);
    entries.value = [];
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  try {
    const index = await logsClient.index();
    kinds.value = index.kinds;
    accounts.value = index.accounts;
    const me = auth.account?.id;
    if (me !== undefined) actors.value = { action: "server", error: me, chat_trace: me };
    tab.value = index.kinds[0] ?? null;
  } catch (err) {
    error.value = errorMessage(err);
  }
});

watch(
  () => [tab.value, tab.value ? actors.value[tab.value] : null],
  () => void loadEntries(),
);
</script>

<template>
  <section class="info-page">
    <div class="column">
      <h2>Logs</h2>
      <div v-if="kinds.length" class="head">
        <div class="tabs" role="tablist">
          <button
            v-for="k in kinds"
            :key="k"
            type="button"
            role="tab"
            :aria-selected="tab === k"
            :class="['chip', { active: tab === k }]"
            @click="tab = k"
          >
            {{ TAB_LABELS[k] }}
          </button>
        </div>
        <label v-if="tab" class="actor">
          Entries for
          <select v-model="actors[tab]">
            <option v-for="o in actorOptions" :key="String(o.value)" :value="o.value">{{ o.label }}</option>
          </select>
        </label>
        <button type="button" class="chip" :disabled="loading" @click="loadEntries">Refresh</button>
      </div>

      <p v-if="error" class="error">{{ error }}</p>
      <p v-else-if="loading" class="muted">loading ...</p>
      <p v-else-if="tab && entries.length === 0" class="muted">No entries yet.</p>

      <ul v-if="!loading" class="entries">
        <li v-for="e in entries" :key="e.id">
          <div class="line">
            <span class="time">{{ time(e.created_at) }}</span>
            <code class="source">{{ e.source }}</code>
            <span class="message">{{ e.message }}</span>
          </div>
          <details v-if="e.details">
            <summary>Details</summary>
            <pre>{{ e.details }}</pre>
          </details>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 16px;
  margin: 12px 0 14px;
}
.tabs {
  display: flex;
  gap: 6px;
}
.actor {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.85em;
  color: var(--muted);
}
.entries {
  margin: 0;
  padding: 0;
  list-style: none;
}
.entries li {
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
  font-size: 0.9em;
}
.line {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 12px;
}
.time {
  color: var(--muted);
  font-size: 0.9em;
  white-space: nowrap;
}
.source {
  font-family: var(--mono);
  font-size: 0.85em;
  color: var(--muted);
}
.message {
  flex: 1 1 300px;
  overflow-wrap: anywhere;
}
details summary {
  cursor: pointer;
  font-size: 0.85em;
  color: var(--muted);
}
</style>
