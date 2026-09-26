<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { usageClient, type AccountUsage, type MyUsage, type UsageWindow } from "../api/UsageClient";
import { useAuthStore } from "../stores/auth";
import { errorMessage, formatUtc } from "../utils/errors";

const auth = useAuthStore();

const RANGES = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
  { days: 365, label: "12 months" },
] as const;

const days = ref<number>(30);
const usage = ref<MyUsage | null>(null);
const accounts = ref<AccountUsage[]>([]);
const loading = ref(false);
const error = ref("");

const isAdmin = computed(() => auth.hasPermission("admin.manage"));

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const [mine, all] = await Promise.all([
      usageClient.mine(days.value),
      isAdmin.value ? usageClient.allAccounts(days.value) : Promise.resolve([]),
    ]);
    usage.value = mine;
    accounts.value = all;
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

function tokens(n: number): string {
  return n.toLocaleString();
}

function percent(window: UsageWindow): number {
  return window.limit ? Math.min(100, Math.round((window.used / window.limit) * 100)) : 0;
}

const maxDaily = computed(() => Math.max(1, ...(usage.value?.report.daily.map((d) => d.tokens) ?? [])));

function dayLabel(date: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
}

watch(days, load);
onMounted(load);
</script>

<template>
  <section class="usage-view">
    <div class="column">
      <div class="head">
        <h2>Usage</h2>
        <div class="ranges" role="group" aria-label="Period">
          <button
            v-for="r in RANGES"
            :key="r.days"
            type="button"
            :class="{ active: days === r.days }"
            :aria-pressed="days === r.days"
            @click="days = r.days"
          >
            {{ r.label }}
          </button>
        </div>
      </div>

      <p v-if="error" class="error">error: {{ error }}</p>
      <p v-else-if="!usage && loading" class="muted">loading ...</p>

      <template v-if="usage">
        <div class="limits">
          <div v-for="w in [{ key: '6 hours', v: usage.six_hour }, { key: '7 days', v: usage.weekly }]" :key="w.key" class="card">
            <div class="limit-head">
              <span>Last {{ w.key }}</span>
              <span class="muted">
                {{ tokens(w.v.used) }}<template v-if="w.v.limit"> / {{ tokens(w.v.limit) }}</template> tokens
              </span>
            </div>
            <div v-if="w.v.limit" class="bar" role="progressbar" :aria-valuenow="percent(w.v)" aria-valuemin="0" aria-valuemax="100">
              <span :class="{ full: percent(w.v) >= 90 }" :style="{ width: `${percent(w.v)}%` }" />
            </div>
            <p v-else class="muted small">No limit.</p>
            <p v-if="w.v.reset_at && w.v.used" class="muted small">
              Oldest tokens stop counting at {{ formatUtc(w.v.reset_at) }}.
            </p>
          </div>
        </div>

        <div class="stats">
          <div class="stat"><strong>{{ tokens(usage.report.total_tokens) }}</strong><span>tokens</span></div>
          <div class="stat"><strong>{{ tokens(usage.report.turns) }}</strong><span>answers</span></div>
          <div class="stat"><strong>{{ tokens(usage.report.chats) }}</strong><span>chats</span></div>
          <div class="stat"><strong>{{ tokens(usage.report.summary_tokens) }}</strong><span>on summaries</span></div>
        </div>

        <h3>Per day</h3>
        <p v-if="usage.report.daily.length === 0" class="muted">No usage in this period.</p>
        <div v-else class="daily">
          <div v-for="d in usage.report.daily" :key="d.date" class="day" :title="`${dayLabel(d.date)}: ${tokens(d.tokens)} tokens`">
            <span class="day-bar" :style="{ height: `${Math.max(4, (d.tokens / maxDaily) * 100)}%` }" />
            <span class="day-label">{{ dayLabel(d.date) }}</span>
          </div>
        </div>

        <h3>By agent</h3>
        <p v-if="usage.report.by_agent.length === 0" class="muted">None.</p>
        <table v-else>
          <thead>
            <tr><th>Agent</th><th>Model</th><th class="num">Tokens</th></tr>
          </thead>
          <tbody>
            <tr v-for="a in usage.report.by_agent" :key="`${a.agent}/${a.model}`">
              <td>{{ a.agent }}</td>
              <td>{{ a.model || "-" }}</td>
              <td class="num">{{ tokens(a.tokens) }}</td>
            </tr>
          </tbody>
        </table>

        <template v-if="isAdmin">
          <h3>All accounts</h3>
          <p v-if="accounts.length === 0" class="muted">No usage in this period.</p>
          <table v-else>
            <thead>
              <tr><th>Account</th><th class="num">Tokens</th><th class="num">Answers</th><th>Last used</th></tr>
            </thead>
            <tbody>
              <tr v-for="a in accounts" :key="a.account_id">
                <td>{{ a.username }}</td>
                <td class="num">{{ tokens(a.tokens) }}</td>
                <td class="num">{{ tokens(a.turns) }}</td>
                <td>{{ a.last_used_at ? formatUtc(a.last_used_at) : "-" }}</td>
              </tr>
            </tbody>
          </table>
        </template>
      </template>
    </div>
  </section>
</template>

<style scoped>
.usage-view {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.column {
  max-width: 820px;
  margin: 0 auto;
  padding: 24px 16px;
}
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}
h2 {
  margin: 0;
  font-size: 1.2em;
}
h3 {
  margin: 24px 0 10px;
  font-size: 1em;
}
.ranges {
  display: flex;
  gap: 4px;
}
.ranges button {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  cursor: pointer;
  font-size: 0.85em;
  color: var(--muted);
  background: transparent;
}
.ranges button.active {
  color: var(--text);
  border-color: var(--accent);
}
.limits {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}
.card {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
}
.limit-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 4px 12px;
  margin-bottom: 8px;
  font-size: 0.9em;
}
.bar {
  height: 8px;
  border-radius: 999px;
  overflow: hidden;
  background: var(--code-bg);
}
.bar span {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--accent);
}
.bar span.full {
  background: var(--danger);
}
.small {
  margin: 6px 0 0;
  font-size: 0.8em;
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.stat {
  display: flex;
  flex-direction: column;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
}
.stat strong {
  font-size: 1.3em;
}
.stat span {
  font-size: 0.8em;
  color: var(--muted);
}
.daily {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 140px;
  padding-bottom: 20px;
  overflow-x: auto;
}
.day {
  position: relative;
  display: flex;
  flex: 1 0 14px;
  flex-direction: column;
  justify-content: flex-end;
  height: 100%;
}
.day-bar {
  display: block;
  border-radius: 3px 3px 0 0;
  background: var(--accent);
}
.day-label {
  position: absolute;
  bottom: -18px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 0.65em;
  white-space: nowrap;
  color: var(--muted);
}
.day:not(:first-child):not(:last-child) .day-label {
  display: none;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9em;
}
th,
td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  text-align: left;
}
th {
  color: var(--muted);
  font-weight: 600;
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.muted {
  color: var(--muted);
}
.error {
  color: var(--danger);
}
</style>
