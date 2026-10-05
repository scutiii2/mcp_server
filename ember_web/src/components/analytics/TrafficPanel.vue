<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { trafficClient, type AnalyticsRange, type TrafficReport } from "../../api/TrafficClient";
import { errorMessage } from "../../utils/errors";
import { RANGE_OPTIONS, describeChange, describeRateChange, formatCount, type Change } from "../../utils/logAnalytics";
import { LATENCY_PARTS, STATUS_PARTS, formatPercent, latencyLabel } from "../../utils/trafficAnalytics";
import ActivityChart from "./ActivityChart.vue";
import BarList from "./BarList.vue";
import LineChart from "./LineChart.vue";
import StatTile from "./StatTile.vue";

/** The Analytics page's Traffic tab: requests and upstream calls ember_api has
 * counted (never who made them). Fetches its own report for `range`, and again
 * whenever `refresh` changes; `loading` tells the page's toolbar. */
const props = defineProps<{ range: AnalyticsRange; refresh: number }>();
const loading = defineModel<boolean>("loading", { default: false });

// Rows per ranking; ember_api sends up to ten.
const TOP_SHOWN = 5;
const BAR_COLOR = "var(--kind-action)";

const report = ref<TrafficReport | null>(null);
const error = ref("");

async function load(): Promise<void> {
  const asked = props.range;
  loading.value = true;
  error.value = "";
  try {
    const result = await trafficClient.analytics(asked);
    if (props.range === asked) report.value = result;
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    if (props.range === asked) loading.value = false;
  }
}

const cap = computed(() => report.value?.latency_cap_ms ?? 0);
const latency = (ms: number | null) => latencyLabel(ms, cap.value);
const since = computed(() => RANGE_OPTIONS.find((o) => o.value === report.value?.period)?.long ?? "");
const idle = computed(() => !!report.value && report.value.totals.requests.current === 0 && report.value.upstream.length === 0);

/** A latency's change: relative, unless one side has no requests to measure. */
function latencyChange(current: number | null, previous: number | null): Change {
  if (current === null) return { text: "no requests", direction: "flat" };
  return previous === null ? { text: "new", direction: "new" } : describeChange(current, previous);
}

const requestsPerBucket = computed(
  () => report.value?.series.map((p) => p.requests["2xx"] + p.requests["3xx"] + p.requests["4xx"] + p.requests["5xx"]) ?? [],
);
const errorRatePerBucket = computed(() =>
  requestsPerBucket.value.map((total, i) => (total ? report.value!.series[i]!.requests["5xx"] / total : 0)),
);
const slowestPerBucket = computed(() => report.value?.series.map((p) => p.p95_ms ?? 0) ?? []);

const tiles = computed(() => {
  const totals = report.value!.totals;
  const requests = describeChange(totals.requests.current, totals.requests.previous);
  const errors = describeRateChange(totals.error_rate.current, totals.error_rate.previous);
  const slow = latencyChange(totals.p95_ms.current, totals.p95_ms.previous);
  const failures = describeChange(totals.upstream_failures.current, totals.upstream_failures.previous);
  return [
    { key: "requests", label: "Requests", value: formatCount(totals.requests.current), change: requests, bad: false, trend: requestsPerBucket.value, color: "var(--kind-action)" },
    { key: "errors", label: "Error rate", value: formatPercent(totals.error_rate.current), change: errors, bad: errors.direction === "up", trend: errorRatePerBucket.value, color: "var(--http-5xx)" },
    { key: "slow", label: "Slowest 5%", value: latency(totals.p95_ms.current), change: slow, bad: slow.direction === "up", trend: slowestPerBucket.value, color: "var(--latency-p95)" },
    {
      key: "failures",
      label: "Upstream failures",
      value: formatCount(totals.upstream_failures.current),
      change: failures,
      // More failures is bad; so is a first failure after none.
      bad: totals.upstream_failures.current > 0 && (failures.direction === "up" || failures.direction === "new"),
      trend: undefined,
      color: "var(--http-4xx)",
    },
  ];
});

const latencySeries = computed(() => report.value!.series.map((p) => ({ bucket: p.bucket, values: { p50: p.p50_ms, p95: p.p95_ms } })));
const requestSeries = computed(() => report.value!.series.map((p) => ({ bucket: p.bucket, counts: p.requests })));
const busiest = computed(() => report.value!.routes.busiest.slice(0, TOP_SHOWN).map((r) => ({ key: r.name, label: r.name, count: r.count })));
const slowest = computed(() =>
  report.value!.routes.slowest.slice(0, TOP_SHOWN).map((r) => ({ key: r.name, label: r.name, count: r.p95_ms ?? 0 })),
);
const upstream = computed(() =>
  report.value!.upstream.map((target) => ({
    target,
    summary: `${formatCount(target.calls)} calls · ${formatCount(target.failures)} failed (${formatPercent(target.failure_rate)}) · slowest 5% ${latency(target.p95_ms)}`,
    tools: target.tools.slice(0, TOP_SHOWN).map((t) => ({
      key: t.name,
      label: t.failures ? `${t.name} · ${t.failures} failed` : t.name,
      count: t.calls,
    })),
  })),
);

onMounted(load);
watch(() => [props.range, props.refresh], load);
</script>

<template>
  <p v-if="error" class="error">{{ error }}</p>
  <p v-else-if="!report" class="muted">loading ...</p>
  <div v-if="report" :class="['overview', { dim: loading }]">
    <p v-if="idle" class="muted idle">
      No traffic recorded in the last {{ since }} yet. Counting starts when ember_api is updated to a version that records it.
    </p>

    <div class="tiles">
      <StatTile
        v-for="tile in tiles"
        :key="tile.key"
        :label="tile.label"
        :value="tile.value"
        :change="tile.change"
        :bad="tile.bad"
        :since="since"
        :trend="tile.trend"
        :color="tile.color"
      />
    </div>

    <div class="card">
      <h3>Requests over time</h3>
      <ActivityChart :series="requestSeries" :parts="STATUS_PARTS" :bucket="report.bucket" noun="requests" />
    </div>

    <div class="card">
      <h3>Response time</h3>
      <LineChart
        :series="latencySeries"
        :lines="LATENCY_PARTS"
        :bucket="report.bucket"
        label="Response time"
        :format="latency"
        empty-text="No requests in this range."
      />
      <p class="hint">
        Time to the first byte of the answer. Kept in bands, so a time is the upper end of its band; {{ latency(cap) }} means at least that.
      </p>
    </div>

    <div class="pair">
      <div class="card">
        <h3>Busiest routes</h3>
        <BarList :items="busiest" :color="BAR_COLOR" empty-text="No requests in this range." />
      </div>
      <div class="card">
        <h3>Slowest routes</h3>
        <BarList :items="slowest" :color="BAR_COLOR" :format="latency" empty-text="No route has enough requests yet." />
        <p class="hint">Slowest 5% of requests; routes with fewer than 5 requests are left out.</p>
      </div>
    </div>

    <div class="card">
      <h3>Upstream calls</h3>
      <p v-if="upstream.length === 0" class="muted">No calls to ai_agent or mcp_server in this range.</p>
      <div v-for="group in upstream" :key="group.target.target" class="group">
        <h4>{{ group.target.target }}</h4>
        <p class="summary">{{ group.summary }}</p>
        <BarList :items="group.tools" :color="BAR_COLOR" />
      </div>
    </div>
  </div>
</template>

<style scoped src="./overview.css"></style>
<style scoped>
.idle {
  margin: 0 0 12px;
}
.hint {
  margin: 8px 0 0;
  font-size: 0.78em;
  color: var(--muted);
}
.summary {
  margin: 0 0 4px 6px;
  font-size: 0.8em;
  color: var(--muted);
}
.group h4 {
  font-family: var(--mono);
}
</style>
