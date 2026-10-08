<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { logsClient, type LogActor, type LogEntry, type LogKind } from "../api/LogsClient";
import SegmentedControl from "./SegmentedControl.vue";
import { useAuthStore } from "../stores/auth";
import { errorMessage } from "../utils/errors";
import { KIND_LABELS } from "../utils/logAnalytics";

/** The raw log entries: Activity, error and chat-turn lists (port of chat_app's Logs page). Each
 * tab needs its own permission; each shows one actor at a time - the
 * server or one account - newest first, the latest 200. `kind` and `actor`
 * open it on that list (read once, when the component is created). */
const props = defineProps<{ kind?: LogKind; actor?: LogActor }>();

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

const tabOptions = computed(() => kinds.value.map((k) => ({ value: k, label: KIND_LABELS[k] })));
// The segmented control needs a chosen kind; the tabs only show once there are kinds.
const tabChoice = computed<LogKind>({
  get: () => tab.value ?? kinds.value[0]!,
  set: (kind) => (tab.value = kind),
});

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
    const first = props.kind && index.kinds.includes(props.kind) ? props.kind : (index.kinds[0] ?? null);
    if (first && props.actor !== undefined && first === props.kind) actors.value[first] = props.actor;
    tab.value = first;
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
  <div v-if="kinds.length" class="head">
    <SegmentedControl v-model="tabChoice" :options="tabOptions" label="Log" aria-label="Log" />
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
</template>

<style scoped>
.head {
  align-items: last baseline;
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  margin: 12px 0 14px;
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
