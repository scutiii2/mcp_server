<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { usageClient, type AccountUsage, type MyUsage, type UsageGroupBy, type UsageRecordRow } from "../api/UsageClient";
import { ApiError } from "../api/http";
import ActionButton from "../components/ActionButton.vue";
import SegmentedControl from "../components/SegmentedControl.vue";
import UsageDetails from "../components/usage/UsageDetails.vue";
import { useAuthStore } from "../stores/auth";
import { downloadText, exportFileName } from "../utils/downloadText";
import { errorMessage, formatUtc } from "../utils/errors";
import { usageToMarkdown } from "../utils/usageExport";
import { monthStart, utcDay } from "../utils/usageStats";

const auth = useAuthStore();
const RANGES = [
  { value: "month", label: "This month", days: 30 },
  { value: "7d", label: "7 days", days: 7 },
  { value: "30d", label: "30 days", days: 30 },
  { value: "90d", label: "90 days", days: 90 },
  { value: "12m", label: "12 months", days: 365 },
] as const;
type RangeKey = (typeof RANGES)[number]["value"];
const range = ref<RangeKey>("30d");
const groupBy = ref<UsageGroupBy>("agent");
const currentRange = computed(() => RANGES.find(r => r.value === range.value)!);
function period() { return { days: currentRange.value.days, since: range.value === "month" ? monthStart(new Date()) : undefined }; }
const accounts = ref<AccountUsage[]>([]);
const selected = ref<AccountUsage | null>(null);
const summaryLoading = ref(false);
const summaryError = ref("");
const detailLoading = ref(false);
const detailError = ref("");
const loaded = ref<{ usage: MyUsage; username: string; rangeLabel: string; rangeKey: RangeKey } | null>(null);
const records = ref<UsageRecordRow[]>([]);
const recordsFailed = ref(false);
const year = ref<MyUsage | null>(null);
const yearFailed = ref(false);
let summaryRequest = 0;
let detailRequest = 0;
let yearRequest = 0;

function clearDetail() {
  ++detailRequest;
  ++yearRequest;
  loaded.value = null;
  records.value = [];
  recordsFailed.value = false;
  year.value = null;
  yearFailed.value = false;
  detailError.value = "";
  detailLoading.value = false;
}

async function loadSummary() {
  const request = ++summaryRequest;
  summaryLoading.value = true;
  summaryError.value = "";
  accounts.value = [];
  const { days, since } = period();
  try {
    const rows = await usageClient.allAccounts(days, since);
    if (request !== summaryRequest) return;
    accounts.value = rows;
    if (selected.value && !rows.some(row => row.account_id === selected.value!.account_id)) selected.value = null;
  } catch (err) {
    if (request === summaryRequest) summaryError.value = errorMessage(err);
  } finally {
    if (request === summaryRequest) summaryLoading.value = false;
  }
}

function deletedTarget() {
  selected.value = null;
  void loadSummary();
}

async function loadDetails() {
  const user = selected.value;
  if (!user) return;
  const request = ++detailRequest;
  loaded.value = null;
  records.value = [];
  recordsFailed.value = false;
  detailError.value = "";
  detailLoading.value = true;
  const { days, since } = period();
  const rangeLabel = currentRange.value.label;
  const rangeKey = range.value;
  try {
    let failed = false;
    const [report, rows] = await Promise.all([
      usageClient.account(user.account_id, days, since, { groupBy: groupBy.value }),
      usageClient.records(user.account_id, days, since, { limit: 100 }).catch(err => {
        if (err instanceof ApiError && err.status === 404) throw err;
        failed = true;
        return [];
      }),
    ]);
    if (request !== detailRequest) return;
    loaded.value = { usage: report, username: user.username, rangeLabel, rangeKey };
    records.value = rows;
    recordsFailed.value = failed;
  } catch (err) {
    if (request !== detailRequest) return;
    if (err instanceof ApiError && err.status === 404) deletedTarget();
    else detailError.value = errorMessage(err);
  } finally {
    if (request === detailRequest) detailLoading.value = false;
  }
}

async function loadYear() {
  const user = selected.value;
  if (!user) return;
  const request = ++yearRequest;
  year.value = null;
  yearFailed.value = false;
  try {
    const report = await usageClient.account(user.account_id, 366);
    if (request === yearRequest) year.value = report;
  } catch (err) {
    if (request !== yearRequest) return;
    if (err instanceof ApiError && err.status === 404) deletedTarget();
    else yearFailed.value = true;
  }
}

function exportReport() {
  const snapshot = loaded.value;
  if (!snapshot) return;
  const now = new Date();
  downloadText(exportFileName(`usage-${snapshot.username}-${snapshot.rangeKey}-${utcDay(now)}`, "md"),
    usageToMarkdown(snapshot.usage.report, { username: snapshot.username, rangeLabel: snapshot.rangeLabel, generatedAt: now }), "text/markdown");
}

watch(() => selected.value?.account_id, () => {
  clearDetail();
  if (selected.value) { void loadDetails(); void loadYear(); }
}, { flush: "sync" });
watch(range, () => { void loadSummary(); void loadDetails(); }, { flush: "sync" });
watch(groupBy, () => { void loadDetails(); }, { flush: "sync" });
watch(() => auth.account?.id, () => {
  ++summaryRequest;
  accounts.value = [];
  selected.value = null;
  clearDetail();
  summaryLoading.value = false;
  summaryError.value = "";
  if (auth.hasPermission("usage.all.view")) void loadSummary();
}, { flush: "sync" });
onBeforeUnmount(() => { ++summaryRequest; clearDetail(); });
onMounted(() => { if (auth.hasPermission("usage.all.view")) void loadSummary(); });
</script>

<template>
  <section class="usage-view">
    <div class="column page-column">
      <header class="head">
        <div><h2 class="page-title">Usage</h2><p class="page-description">Review each user's token usage and account limits.</p></div>
        <div class="ranges">
          <SegmentedControl v-model="range" :options="RANGES" label="Period" aria-label="Period" />
          <ActionButton icon="export" class="export" :disabled="!loaded" title="Download the selected user's usage as Markdown" @click="exportReport">Export .md</ActionButton>
        </div>
      </header>
      <section class="panel accounts" aria-label="User usage summary" :aria-busy="summaryLoading">
        <h3>All users</h3>
        <p v-if="summaryError" class="error" role="alert">Could not load user usage: {{ summaryError }} <button class="summary-retry" @click="loadSummary">Retry</button></p>
        <p v-else-if="summaryLoading" class="muted" role="status">Loading user usage…</p>
        <p v-else-if="accounts.length === 0" class="muted">No accounts.</p>
        <table v-else>
          <thead><tr><th>User</th><th class="num">Tokens</th><th class="num">Answers</th><th>Last used in period</th></tr></thead>
          <tbody><tr v-for="user in accounts" :key="user.account_id" :class="{ selected: selected?.account_id === user.account_id }">
            <td><button type="button" :aria-label="`View usage for ${user.username}`" :aria-pressed="selected?.account_id === user.account_id" @click="selected = user">{{ user.username }}</button></td>
            <td class="num">{{ user.tokens.toLocaleString() }}</td><td class="num">{{ user.turns.toLocaleString() }}</td>
            <td>{{ user.last_used_at ? formatUtc(user.last_used_at) : 'No usage' }}</td>
          </tr></tbody>
        </table>
      </section>
      <p v-if="!selected" class="muted">Select a user to view their usage.</p>
      <p v-else-if="detailLoading" class="muted" role="status">Loading usage for {{ selected.username }}…</p>
      <p v-else-if="detailError" class="error" role="alert">Could not load usage for {{ selected.username }}: {{ detailError }} <button class="detail-retry" @click="loadDetails">Retry</button></p>
      <UsageDetails v-if="loaded" :username="loaded.username" :usage="loaded.usage" :year="year" :records="records" :records-failed="recordsFailed" :year-failed="yearFailed" :loading="detailLoading" :group-by="groupBy" @group="groupBy = $event" />
    </div>
  </section>
</template>

<style scoped>
.usage-view { flex: 1; min-width: 0; min-height: 0; overflow-y: auto; }
.head, .ranges { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.ranges { min-width: 0; max-width: 100%; }
.ranges > .segmented-control { flex: 1 1 auto; }
.head { justify-content: space-between; margin-bottom: 16px; }
.panel { padding: 14px; margin-bottom: 20px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface); }
h3 { margin: 0 0 12px; font-size: 1em; }
table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
th, td { text-align: left; padding: 10px 6px; border-bottom: 1px solid var(--border); overflow-wrap: anywhere; }
.num { text-align: right; }
button { padding: 6px 10px; border: 1px solid var(--border); border-radius: var(--radius-md); color: var(--text); background: var(--bg); cursor: pointer; }
button:hover, button[aria-pressed="true"] { border-color: var(--accent); color: var(--accent); }
button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.selected { background: color-mix(in srgb, var(--accent) 8%, var(--surface)); }
.muted { color: var(--muted); }
.error { color: var(--danger); }
@media (max-width: 767px) { table { table-layout: fixed; font-size: 0.8em; } th, td { padding: 8px 3px; } td button { max-width: 100%; overflow-wrap: anywhere; } }
</style>
