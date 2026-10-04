<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref } from "vue";
import { watchersClient, type WatcherInfo } from "../api/WatchersClient";
import "../components/infoPage.css";
import { errorMessage } from "../utils/errors";

/** Status of mcp_server's background watchers, every capability's (port of
 * chat_app's Watchers page). Read-only and live: refreshed every 15 s;
 * filtering happens here on the rows already fetched. */

const REFRESH_MS = 15_000;

type StatusChip = "running" | "completed" | "failed";
const STATUS_LABELS: Record<string, string> = {
  running: "Running",
  completed: "Success",
  failed: "Failed",
  timed_out: "Failed",
};
// The "Failed" chip covers timed-out watchers too.
const CHIP_PHASES: Record<StatusChip, string[]> = {
  running: ["running"],
  completed: ["completed"],
  failed: ["failed", "timed_out"],
};

const watchers = ref<WatcherInfo[]>([]);
const loading = ref(true);
const error = ref("");
const partialErrors = ref<string[]>([]);
const now = ref(Date.now());

// Filters. Capabilities start all on; one seen for the first time joins on.
const hiddenCapabilities = ref(new Set<string>());
const statuses = ref(new Set<StatusChip>(["running", "completed", "failed"]));
const startedFrom = ref("");
const startedUntil = ref("");
const search = ref("");

const capabilities = computed(() => [...new Set(watchers.value.map((w) => w.capability))].sort());

function keyOf(w: WatcherInfo): string {
  return w.key ?? w.name ?? "";
}

const shown = computed(() => {
  const phases = new Set([...statuses.value].flatMap((s) => CHIP_PHASES[s]));
  const from = startedFrom.value ? Date.parse(startedFrom.value) : null;
  const until = startedUntil.value ? Date.parse(startedUntil.value) : null;
  const needle = search.value.trim().toLowerCase();
  return watchers.value.filter((w) => {
    if (hiddenCapabilities.value.has(w.capability) || !phases.has(w.phase)) return false;
    const started = w.started_at ? Date.parse(w.started_at) : NaN;
    if (from !== null && !(started >= from)) return false;
    if (until !== null && !(started <= until)) return false;
    return !needle || `${w.capability} ${keyOf(w)}`.toLowerCase().includes(needle);
  });
});

function toggle<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  if (!next.delete(value)) next.add(value);
  return next;
}

function clearFilters(): void {
  hiddenCapabilities.value = new Set();
  statuses.value = new Set(["running", "completed", "failed"]);
  startedFrom.value = startedUntil.value = search.value = "";
}

function formatTime(iso?: string): string {
  return iso ? new Date(iso).toLocaleString() : "";
}

function duration(w: WatcherInfo): string {
  if (!w.started_at) return "";
  const end = w.phase === "running" ? now.value : w.last_polled_at ? Date.parse(w.last_polled_at) : NaN;
  let seconds = Math.max(0, Math.round((end - Date.parse(w.started_at)) / 1000));
  if (Number.isNaN(seconds)) return "";
  const hours = Math.floor(seconds / 3600);
  seconds -= hours * 3600;
  const minutes = Math.floor(seconds / 60);
  seconds -= minutes * 60;
  return [hours ? `${hours}h` : "", hours || minutes ? `${minutes}m` : "", `${seconds}s`].filter(Boolean).join(" ");
}

async function refresh(): Promise<void> {
  try {
    const report = await watchersClient.list();
    watchers.value = report.watchers;
    partialErrors.value = report.errors;
    error.value = "";
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    loading.value = false;
    now.value = Date.now();
  }
}

// Only while the page is shown (it may be kept alive in the background).
let timer: ReturnType<typeof setInterval> | null = null;
function startTimer(): void {
  stopTimer();
  timer = setInterval(() => void refresh(), REFRESH_MS);
}
function stopTimer(): void {
  if (timer !== null) clearInterval(timer);
  timer = null;
}
onMounted(() => {
  void refresh();
  startTimer();
});
onActivated(startTimer);
onDeactivated(stopTimer);
onUnmounted(stopTimer);
</script>

<template>
  <section class="info-page">
    <div class="column">
      <h2>Watchers</h2>
      <p class="muted intro">
        Background jobs mcp_server's capabilities are watching. Refreshed every 15 seconds; recipients are set on the
        mcp_server side.
      </p>

      <p v-if="error" class="error">Could not reach mcp_server: {{ error }}</p>
      <p v-else-if="partialErrors.length" class="error">Some capabilities didn't answer: {{ partialErrors.join("; ") }}</p>

      <div class="filters">
        <div v-if="capabilities.length" class="group">
          <span class="label">Capability</span>
          <button
            v-for="c in capabilities"
            :key="c"
            type="button"
            :class="['chip', { active: !hiddenCapabilities.has(c) }]"
            @click="hiddenCapabilities = toggle(hiddenCapabilities, c)"
          >
            {{ c }}
          </button>
        </div>
        <div class="group">
          <span class="label">Status</span>
          <button
            v-for="s in ['running', 'completed', 'failed'] as const"
            :key="s"
            type="button"
            :class="['chip', { active: statuses.has(s) }]"
            @click="statuses = toggle(statuses, s)"
          >
            {{ STATUS_LABELS[s] }}
          </button>
        </div>
        <label class="group">
          <span class="label">Started from</span>
          <input v-model="startedFrom" type="datetime-local" />
        </label>
        <label class="group">
          <span class="label">until</span>
          <input v-model="startedUntil" type="datetime-local" />
        </label>
        <input v-model="search" type="search" placeholder="Search" class="search" />
        <button type="button" class="chip" @click="clearFilters">Clear filters</button>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Watcher</th>
              <th>Status</th>
              <th>Duration</th>
              <th>Recipients</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading">
              <td colspan="4" class="muted">Loading …</td>
            </tr>
            <tr v-else-if="shown.length === 0">
              <td colspan="4" class="muted">
                {{ watchers.length ? "No watchers match the filters." : "No watchers are running." }}
              </td>
            </tr>
            <tr v-for="w in shown" :key="`${w.capability}/${keyOf(w)}`">
              <td>
                {{ keyOf(w) }}<br /><span class="muted">{{ w.capability }}</span>
                <details v-if="w.detail && Object.keys(w.detail).length">
                  <summary>Detail</summary>
                  <pre>{{ JSON.stringify(w.detail, null, 2) }}</pre>
                </details>
              </td>
              <td>
                <span :class="['badge', w.phase]">{{ STATUS_LABELS[w.phase] ?? w.phase }}</span>
              </td>
              <td>
                {{ duration(w) }}<br />
                <span class="muted">Started {{ formatTime(w.started_at) }}</span>
                <template v-if="w.phase !== 'running' && w.last_polled_at">
                  <br /><span class="muted">Finished {{ formatTime(w.last_polled_at) }}</span>
                </template>
              </td>
              <td>
                <template v-if="w.recipients?.length">
                  <div v-for="r in w.recipients" :key="r">{{ r }}</div>
                </template>
                <span v-else class="muted">none</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 16px;
  margin-bottom: 14px;
}
.group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.label {
  font-size: 0.8em;
  color: var(--muted);
}
.search {
  flex: 0 1 200px;
  min-width: 0;
}
.badge {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 0.8em;
  white-space: nowrap;
  border: 1px solid var(--border);
}
.badge.running {
  border-color: var(--accent);
  color: var(--accent);
}
.badge.completed {
  border-color: #2e9d5b;
  color: #2e9d5b;
}
.badge.failed,
.badge.timed_out {
  border-color: var(--danger);
  color: var(--danger);
}
</style>
