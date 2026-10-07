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
        failed = true; // the list is extra: the report still shows
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

const GROUP_OPTIONS: { value: UsageGroupBy; label: string }[] = [
  { value: "agent", label: "Agent" },
  { value: "model", label: "Model" },
  { value: "provider", label: "Provider" },
  { value: "gateway", label: "Gateway" },
];
const GROUP_HEADINGS = Object.fromEntries(GROUP_OPTIONS.map((o) => [o.value, o.label])) as Record<UsageGroupBy, string>;
// The heading follows the loaded report, not the selector, which may already show the next choice.
const groupHeading = computed(() => GROUP_HEADINGS[usage.value?.report.group_by ?? groupBy.value]);

/** A naive-UTC API time as the viewer's local date and time. */
function localTime(value: string): string {
  return new Date(parseServerTime(value)).toLocaleString();
}

function tokens(n: number): string {
  return n.toLocaleString();
}

// Each group's share of the grouped total, for its bar.
const groupTotal = computed(() => Math.max(1, usage.value?.report.groups.reduce((sum, g) => sum + g.tokens, 0) ?? 0));

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
        <div class="panel limits">
          <div class="panel-head"><h3>Limits</h3><span class="muted small">Rolling windows</span></div>
          <div class="limit-grid">
            <div v-for="w in [{ key: '6 hours', v: usage.six_hour }, { key: '7 days', v: usage.weekly }]" :key="w.key">
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
        </div>

        <div class="stats">
          <div class="stat"><strong>{{ tokens(usage.report.total_tokens) }}</strong><span>tokens</span></div>
          <div class="stat"><strong>{{ tokens(usage.report.turns) }}</strong><span>answers</span></div>
          <div class="stat"><strong>{{ tokens(usage.report.chats) }}</strong><span>chats</span></div>
        </div>

        <div class="panel activity">
          <div class="panel-head"><h3>Activity</h3><span class="muted small">Per day, UTC</span></div>
          <p v-if="usage.report.daily.length === 0" class="muted">No usage in this period.</p>
          <div v-else class="daily">
            <div v-for="d in usage.report.daily" :key="d.date" class="day" :title="`${dayLabel(d.date)}: ${tokens(d.tokens)} tokens`">
              <span class="day-bar" :style="{ height: `${Math.max(4, (d.tokens / maxDaily) * 100)}%` }" />
              <span class="day-label">{{ dayLabel(d.date) }}</span>
            </div>
          </div>

          <template v-if="year">
            <h4>Last 12 months</h4>
            <UsageHeatmap v-if="year.report.daily.length" :daily="year.report.daily" :today="today" />
            <p v-else class="muted">No usage in the last 12 months.</p>
            <p class="muted small">Days are UTC days.</p>
          </template>

          <p v-if="peak !== null || favorite" class="insights">
            <span v-if="peak !== null" class="insight">Busiest hour (your time) <strong>{{ hourLabel(peak) }}</strong></span>
            <span v-if="favorite" class="insight">Favorite agent <strong>{{ favorite }}</strong></span>
            <span class="insight">Active days <strong>{{ usage.report.daily.length }}</strong></span>
          </p>
        </div>

        <div class="panel breakdown">
          <div class="panel-head">
            <h3>Breakdown</h3>
            <SegmentedControl v-model="groupBy" :options="GROUP_OPTIONS" aria-label="Group usage by" />
          </div>
          <p v-if="usage.report.groups.length === 0" class="muted">None.</p>
          <table v-else class="groups">
            <thead>
              <tr><th>{{ groupHeading }}</th><th>Share</th><th class="num">Tokens</th><th class="num">Turns</th></tr>
            </thead>
            <tbody>
              <tr v-for="g in usage.report.groups" :key="g.key">
                <td>{{ g.key }}</td>
                <td class="share">
                  <div class="bar"><span :style="{ width: `${Math.round((g.tokens / groupTotal) * 100)}%` }" /></div>
                  <span class="muted small">{{ tokens(g.input_tokens) }} in · {{ tokens(g.output_tokens) }} out</span>
                </td>
                <td class="num">{{ tokens(g.tokens) }}</td>
                <td class="num">{{ g.turns }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="panel recent">
          <div class="panel-head"><h3>Recent calls</h3><span class="muted small">Last 100</span></div>
          <p v-if="recordsFailed" class="muted">Could not load recent calls.</p>
          <p v-else-if="records.length === 0" class="muted">None.</p>
          <ul v-else class="calls">
            <li v-for="r in records" :key="r.id" class="call">
              <div class="call-main">
                <div>
                  <span class="call-agent">{{ r.agent_id ?? r.agent ?? "unknown" }}</span>
                  <span v-if="r.delegated_by" class="muted"> ← {{ r.delegated_by }}</span>
                  <span v-if="r.provider_id" class="chip">{{ r.provider_id }}</span>
                  <span v-if="r.gateway" class="chip">{{ r.gateway }}</span>
                </div>
                <div class="muted small">{{ localTime(r.started_at ?? r.created_at) }}<template v-if="r.model"> · {{ r.model }}</template></div>
              </div>
              <div class="call-tokens">
                <strong>{{ tokens(r.total_tokens) }}</strong>
                <span v-if="r.input_tokens !== null && r.output_tokens !== null" class="muted small">
                  {{ tokens(r.input_tokens) }} in / {{ tokens(r.output_tokens) }} out
                </span>
              </div>
            </li>
          </ul>
        </div>

        <div v-if="isAdmin" class="panel accounts">
          <div class="panel-head"><h3>All accounts</h3><span class="muted small">Admin only</span></div>
          <p v-if="accounts.length === 0" class="muted">No usage in this period.</p>
          <ul v-else class="calls">
            <li v-for="a in accounts" :key="a.account_id" class="call">
              <div class="call-main">
                <div class="call-agent">{{ a.username }}</div>
                <div class="muted small">{{ tokens(a.turns) }} answers · last used {{ a.last_used_at ? formatUtc(a.last_used_at) : "-" }}</div>
              </div>
              <div class="call-tokens"><strong>{{ tokens(a.tokens) }}</strong></div>
            </li>
          </ul>
        </div>
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
  margin: 0;
  font-size: 1em;
}
h4 {
  margin: 16px 0 8px;
  font-size: 0.85em;
  font-weight: 600;
  color: var(--muted);
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
.panel {
  margin-top: 12px;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.panel-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 12px;
  margin-bottom: 12px;
}
.panel-head .small {
  margin: 0;
}
.limit-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
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
  height: 6px;
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
  border-radius: var(--radius-md);
  background: var(--code-bg);
}
.stat strong {
  font-size: 1.3em;
  font-variant-numeric: tabular-nums;
}
.stat span {
  font-size: 0.8em;
  color: var(--muted);
}
.insights {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  margin: 14px 0 0;
  font-size: 0.8em;
  color: var(--muted);
}
.insight strong {
  font-weight: 600;
  color: var(--text);
}
.daily {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 110px;
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
  border-radius: 2px 2px 0 0;
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
  padding: 8px;
  border-top: 1px solid var(--border);
  text-align: left;
  vertical-align: middle;
}
th {
  padding-top: 0;
  border-top: none;
  font-size: 0.8em;
  font-weight: 500;
  color: var(--muted);
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.share {
  width: 45%;
}
.share .small {
  display: block;
  margin-top: 3px;
}
.calls {
  margin: 0;
  padding: 0;
  list-style: none;
}
.call {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 0;
  border-top: 1px solid var(--border);
  font-size: 0.9em;
}
.call:first-child {
  padding-top: 0;
  border-top: none;
}
.call-main {
  min-width: 0;
  overflow-wrap: anywhere;
}
.call-agent {
  font-weight: 500;
}
.call-main .small {
  margin: 2px 0 0;
}
.call-tokens {
  display: flex;
  flex: none;
  flex-direction: column;
  align-items: flex-end;
  font-variant-numeric: tabular-nums;
}
.call-tokens .small {
  margin: 2px 0 0;
}
.chip {
  margin-left: 6px;
  padding: 1px 8px;
  border-radius: var(--radius-full);
  font-size: 0.8em;
  color: var(--muted);
  background: var(--code-bg);
}
.muted {
  color: var(--muted);
}
.error {
  color: var(--danger);
}
</style>
