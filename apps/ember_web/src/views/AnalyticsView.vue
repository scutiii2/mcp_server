<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { logsClient, type AnalyticsRange, type AnalyticsReport, type LogActor, type LogKind } from "../api/LogsClient";
import ActivityChart from "../components/analytics/ActivityChart.vue";
import BarList from "../components/analytics/BarList.vue";
import HourHeatmap from "../components/analytics/HourHeatmap.vue";
import KindStatTile from "../components/analytics/KindStatTile.vue";
import TrafficPanel from "../components/analytics/TrafficPanel.vue";
import "../components/infoPage.css";
import LogEntries from "../components/LogEntries.vue";
import SegmentedControl from "../components/SegmentedControl.vue";
import { LOG_PERMISSIONS } from "../router/pages";
import { useAuthStore } from "../stores/auth";
import { errorMessage } from "../utils/errors";
import { KIND_COLORS, KIND_LABELS, RANGE_OPTIONS, accountLabel } from "../utils/logAnalytics";

/** Analytics page (was Logs): charts over the log entries (Overview), network
 * traffic (Traffic) and the entries themselves (Entries). Any `logs.*` permission
 * opens Overview and Entries and `traffic.view` opens Traffic; ember_api only
 * counts the kinds the account may read, so the page just draws what it gets. */

type Tab = "overview" | "traffic" | "entries";

// Rows per kind in the ranking cards; ember_api sends up to ten.
const TOP_SHOWN = 5;

const auth = useAuthStore();
const canLogs = computed(() => LOG_PERMISSIONS.some((permission) => auth.hasPermission(permission)));
const canTraffic = computed(() => auth.hasPermission("traffic.view"));
const TAB_OPTIONS = computed<{ value: Tab; label: string }[]>(() => [
  ...(canLogs.value ? [{ value: "overview" as const, label: "Overview" }] : []),
  ...(canTraffic.value ? [{ value: "traffic" as const, label: "Traffic" }] : []),
  ...(canLogs.value ? [{ value: "entries" as const, label: "Entries" }] : []),
]);

const tab = ref<Tab>(canLogs.value ? "overview" : "traffic");
const range = ref<AnalyticsRange>("7d");
const report = ref<AnalyticsReport | null>(null);
const loading = ref(false);
const error = ref("");
// Set when an account's row was clicked: the Entries tab opens on its list.
const jump = ref<{ kind: LogKind; actor: LogActor } | null>(null);
// The Traffic tab fetches its own report; this asks it to fetch again.
const trafficRefresh = ref(0);
const trafficLoading = ref(false);
const busy = computed(() => (tab.value === "traffic" ? trafficLoading.value : loading.value));

const kindParts = computed(() =>
  (report.value?.kinds ?? []).map((kind) => ({ id: kind, label: KIND_LABELS[kind], color: KIND_COLORS[kind] })),
);
const trend = (kind: LogKind): number[] => report.value?.series.map((p) => p.counts[kind] ?? 0) ?? [];
const sources = computed(() =>
  (report.value?.kinds ?? []).map((kind) => ({
    kind,
    items: (report.value?.top_sources[kind] ?? []).slice(0, TOP_SHOWN).map((s) => ({ key: s.source, label: s.source, count: s.count })),
  })),
);
const accounts = computed(() =>
  (report.value?.kinds ?? []).map((kind) => ({
    kind,
    items: (report.value?.accounts[kind] ?? []).slice(0, TOP_SHOWN).map((a) => ({
      key: (a.account_id ?? "server") as LogActor,
      label: accountLabel(a),
      count: a.count,
    })),
  })),
);

async function load(): Promise<void> {
  if (!canLogs.value) return;
  const asked = range.value;
  loading.value = true;
  error.value = "";
  try {
    const result = await logsClient.analytics(asked);
    if (range.value === asked) report.value = result;
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    if (range.value === asked) loading.value = false;
  }
}

function showTab(next: Tab): void {
  jump.value = null;
  tab.value = next;
}

function refresh(): void {
  if (tab.value === "traffic") trafficRefresh.value += 1;
  else void load();
}

function openEntries(kind: LogKind, actor: LogActor): void {
  jump.value = { kind, actor };
  tab.value = "entries";
}

onMounted(load);
watch(range, load);
</script>

<template>
  <section class="info-page">
    <div class="column">
      <h2>Analytics</h2>
      <div class="toolbar">
        <SegmentedControl :model-value="tab" :options="TAB_OPTIONS" label="View" aria-label="View" @update:model-value="showTab" />
        <template v-if="tab !== 'entries'">
          <SegmentedControl v-model="range" :options="RANGE_OPTIONS" label="Period" aria-label="Range" />
          <button type="button" class="chip" :disabled="busy" @click="refresh">Refresh</button>
          <span class="note">Times in UTC</span>
        </template>
      </div>

      <template v-if="tab === 'overview'">
        <p v-if="error" class="error">{{ error }}</p>
        <p v-else-if="!report" class="muted">loading ...</p>
        <div v-if="report" :class="['overview', { dim: loading }]">
          <div class="tiles">
            <KindStatTile
              v-for="kind in report.kinds"
              :key="kind"
              :kind="kind"
              :total="report.totals[kind]!"
              :trend="trend(kind)"
              :range="report.period"
            />
          </div>

          <div class="card">
            <h3>Over time</h3>
            <ActivityChart :series="report.series" :parts="kindParts" :bucket="report.bucket" noun="entries" />
          </div>

          <div class="pair">
            <div class="card">
              <h3>Top sources</h3>
              <div v-for="group in sources" :key="group.kind" class="group">
                <h4><span class="key" :style="{ background: KIND_COLORS[group.kind] }" />{{ KIND_LABELS[group.kind] }}</h4>
                <BarList :items="group.items" :color="KIND_COLORS[group.kind]" />
              </div>
            </div>
            <div class="card">
              <h3>Busiest accounts</h3>
              <div v-for="group in accounts" :key="group.kind" class="group">
                <h4><span class="key" :style="{ background: KIND_COLORS[group.kind] }" />{{ KIND_LABELS[group.kind] }}</h4>
                <BarList
                  :items="group.items"
                  :color="KIND_COLORS[group.kind]"
                  selectable
                  @select="(actor) => openEntries(group.kind, actor)"
                />
              </div>
            </div>
          </div>

          <div class="card">
            <h3>When it happens</h3>
            <HourHeatmap :cells="report.heatmap" />
          </div>
        </div>
      </template>

      <TrafficPanel v-else-if="tab === 'traffic'" v-model:loading="trafficLoading" :range="range" :refresh="trafficRefresh" />

      <LogEntries v-else :kind="jump?.kind" :actor="jump?.actor" />
    </div>
  </section>
</template>

<style scoped src="../components/analytics/overview.css"></style>
<style scoped>
.toolbar {
  align-items: last baseline;
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  margin: 12px 0 16px;
}
.note {
  margin-left: auto;
  font-size: 0.8em;
  color: var(--muted);
}
</style>
