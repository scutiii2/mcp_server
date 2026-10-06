<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { usageClient, type AccountUsage, type MyUsage, type UsageGroupBy, type UsageRecordRow } from "../api/UsageClient";
import SegmentedControl from "../components/SegmentedControl.vue";
import UsageHeatmap from "../components/UsageHeatmap.vue";
import { useAuthStore } from "../stores/auth";
import { downloadText, exportFileName } from "../utils/chatExport";
import { errorMessage, formatUtc } from "../utils/errors";
import { usageToMarkdown } from "../utils/usageExport";
import { parseServerTime, usagePercent as percent } from "../utils/usageFormat";
import { favoriteAgent, hourLabel, monthStart, peakHour, utcDay } from "../utils/usageStats";

const auth = useAuthStore();

// "This month" runs from the 1st (UTC); the others are the last n days.
const RANGES = [
  { key: "month", label: "This month" },
  { key: "7d", label: "7 days", days: 7 },
  { key: "30d", label: "30 days", days: 30 },
  { key: "90d", label: "90 days", days: 90 },
  { key: "12m", label: "12 months", days: 365 },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];
const RANGE_OPTIONS = RANGES.map((r) => ({ value: r.key, label: r.label }));

const range = ref<RangeKey>("30d");
const currentRange = computed(() => RANGES.find((r) => r.key === range.value)!);

/** What to ask ember_api for: `days`, or the 1st of this month as `since`. */
function period(): { days: number; since?: string } {
  const r = currentRange.value;
  return "days" in r ? { days: r.days } : { days: 30, since: monthStart(new Date()) };
}

const today = utcDay(new Date());
// The last 12 months for the heatmap, whatever period is chosen above.
const year = ref<MyUsage | null>(null);
const usage = ref<MyUsage | null>(null);
const accounts = ref<AccountUsage[]>([]);
const groupBy = ref<UsageGroupBy>("agent");
const records = ref<UsageRecordRow[]>([]);
const recordsFailed = ref(false);
const loading = ref(false);
const error = ref("");

const isAdmin = computed(() => auth.hasPermission("admin.manage"));

// Each load takes a number; a response that is no longer the latest request's
// (the period or grouping changed meanwhile) is dropped.
let latestLoad = 0;

async function load(): Promise<void> {
  const mine = ++latestLoad;
  loading.value = true;
  error.value = "";
  try {
    const { days, since } = period();
    let failed = false;
    const [report, all, rows] = await Promise.all([
      usageClient.mine(days, since, { groupBy: groupBy.value }),
      isAdmin.value ? usageClient.allAccounts(days, since) : Promise.resolve([]),
      usageClient.records(days, since, { limit: 100 }).catch(() => {
        failed = true; // the table is extra: the report still shows
        return [];
      }),
    ]);
    if (mine !== latestLoad) return;
    usage.value = report;
    accounts.value = all;
    records.value = rows;
    recordsFailed.value = failed;
  } catch (err) {
    if (mine === latestLoad) error.value = errorMessage(err);
  } finally {
    if (mine === latestLoad) loading.value = false;
  }
}

const GROUP_HEADINGS: Record<UsageGroupBy, string> = { agent: "Agent", provider: "Provider", gateway: "Gateway", model: "Model" };
// The heading follows the loaded report, not the selector, which may already show the next choice.
const groupHeading = computed(() => GROUP_HEADINGS[usage.value?.report.group_by ?? groupBy.value]);

/** A naive-UTC API time as the viewer's local date and time. */
function localTime(value: string): string {
  return new Date(parseServerTime(value)).toLocaleString();
}

function tokens(n: number): string {
  return n.toLocaleString();
}

const maxDaily = computed(() => Math.max(1, ...(usage.value?.report.daily.map((d) => d.tokens) ?? [])));

function dayLabel(date: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
}

async function loadYear(): Promise<void> {
  try {
    year.value = await usageClient.mine(366);
  } catch {
    year.value = null; // the heatmap is extra: the rest of the page still works
  }
}

const peak = computed(() => (usage.value ? peakHour(usage.value.report.hourly) : null));
const favorite = computed(() => (usage.value ? favoriteAgent(usage.value.report.by_agent) : null));

function exportReport(): void {
  const current = usage.value;
  if (!current) return;
  const now = new Date();
  const text = usageToMarkdown(current.report, {
    username: auth.account?.username ?? "me",
    rangeLabel: currentRange.value.label,
    generatedAt: now,
  });
  downloadText(exportFileName(`usage-${range.value}-${utcDay(now)}`, "md"), text, "text/markdown");
}

watch([range, groupBy], load);
onMounted(() => {
  void load();
  void loadYear();
});
</script>

<template>
  <section class="usage-view">
    <div class="column">
      <div class="head">
        <h2>Usage</h2>
        <div class="ranges" role="group" aria-label="Period">
          <SegmentedControl v-model="range" :options="RANGE_OPTIONS" />
          <button type="button" class="export" :disabled="!usage" title="Download this period as a Markdown file" @click="exportReport">
            Export .md
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
          <div v-if="peak !== null" class="stat"><strong>{{ hourLabel(peak) }}</strong><span>busiest hour (your time)</span></div>
          <div v-if="favorite" class="stat"><strong class="text">{{ favorite }}</strong><span>favorite agent</span></div>
        </div>

        <template v-if="year">
          <h3>Last 12 months</h3>
          <UsageHeatmap v-if="year.report.daily.length" :daily="year.report.daily" :today="today" />
          <p v-else class="muted">No usage in the last 12 months.</p>
          <p class="muted small">Days are UTC days.</p>
        </template>

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

        <h3>
          By
          <select v-model="groupBy" class="group-by" aria-label="Group usage by">
            <option value="agent">agent</option>
            <option value="provider">provider</option>
            <option value="gateway">gateway</option>
            <option value="model">model</option>
          </select>
        </h3>
        <p v-if="usage.report.groups.length === 0" class="muted">None.</p>
        <table v-else class="groups">
          <thead>
            <tr><th>{{ groupHeading }}</th><th class="num">Tokens</th><th class="num">In</th><th class="num">Out</th><th class="num">Turns</th></tr>
          </thead>
          <tbody>
            <tr v-for="g in usage.report.groups" :key="g.key">
              <td>{{ g.key }}</td>
              <td class="num">{{ tokens(g.tokens) }}</td>
              <td class="num">{{ tokens(g.input_tokens) }}</td>
              <td class="num">{{ tokens(g.output_tokens) }}</td>
              <td class="num">{{ g.turns }}</td>
            </tr>
          </tbody>
        </table>

        <h3>Recent calls</h3>
        <p v-if="recordsFailed" class="muted">Could not load recent calls.</p>
        <p v-else-if="records.length === 0" class="muted">None.</p>
        <div v-else class="table-scroll">
          <table class="records">
            <thead>
              <tr>
                <th>When</th><th>Agent</th><th>Provider</th><th>Gateway</th><th>Model</th>
                <th class="num">In</th><th class="num">Out</th><th class="num">Total</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in records" :key="r.id">
                <td>{{ localTime(r.started_at ?? r.created_at) }}</td>
                <td>{{ r.agent_id ?? r.agent ?? "unknown" }}<span v-if="r.delegated_by" class="muted"> ← {{ r.delegated_by }}</span></td>
                <td>{{ r.provider_id ?? "-" }}</td>
                <td>{{ r.gateway ?? "-" }}</td>
                <td>{{ r.model ?? "-" }}</td>
                <td class="num">{{ r.input_tokens === null ? "-" : tokens(r.input_tokens) }}</td>
                <td class="num">{{ r.output_tokens === null ? "-" : tokens(r.output_tokens) }}</td>
                <td class="num">{{ tokens(r.total_tokens) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

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
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.ranges .export {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  cursor: pointer;
  font-size: 0.85em;
  color: var(--muted);
  background: transparent;
}
.ranges .export:disabled {
  cursor: default;
  opacity: 0.5;
}
.limits {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}
.card {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
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
  border-radius: var(--radius-full);
  overflow: hidden;
  background: var(--code-bg);
}
.bar span {
  display: block;
  height: 100%;
  border-radius: var(--radius-full);
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
  border-radius: var(--radius-lg);
}
.stat strong {
  font-size: 1.3em;
}
.stat strong.text {
  font-size: 1em;
  overflow-wrap: anywhere;
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
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
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
.group-by {
  padding: 2px 6px;
  font: inherit;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.table-scroll {
  overflow-x: auto;
}
.records td {
  white-space: nowrap;
}
.muted {
  color: var(--muted);
}
.error {
  color: var(--danger);
}
</style>
