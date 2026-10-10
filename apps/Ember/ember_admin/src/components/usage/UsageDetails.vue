<script setup lang="ts">
import { computed } from "vue";
import type { MyUsage, UsageGroupBy, UsageRecordRow } from "../../api/UsageClient";
import SegmentedControl from "../SegmentedControl.vue";
import LineChart from "../analytics/LineChart.vue";
import UsageHeatmap from "../UsageHeatmap.vue";
import { formatUtc } from "../../utils/errors";
import { parseServerTime, usagePercent as percent } from "../../utils/usageFormat";
import { favoriteAgent, hourLabel, peakHour, utcDay } from "../../utils/usageStats";
const props = defineProps<{ username: string; usage: MyUsage; year: MyUsage | null; records: UsageRecordRow[]; recordsFailed: boolean; yearFailed: boolean; loading: boolean; groupBy: UsageGroupBy }>();
const emit = defineEmits<{ group: [value: UsageGroupBy] }>();
const groupBy = computed({ get: () => props.groupBy, set: value => emit("group", value) });
const today = utcDay(new Date());
const GROUP_OPTIONS: { value: UsageGroupBy; label: string }[] = [{ value: "agent", label: "Agent" }, { value: "model", label: "Model" }, { value: "provider", label: "Provider" }, { value: "gateway", label: "Gateway" }];
const groupHeading = computed(() => GROUP_OPTIONS.find(o => o.value === props.usage.report.group_by)?.label ?? "Agent");
const groupTotal = computed(() => Math.max(1, props.usage.report.groups.reduce((sum, g) => sum + g.tokens, 0)));
function tokens(n: number): string { return n.toLocaleString(); }
function localTime(value: string): string { return new Date(parseServerTime(value)).toLocaleString(); }
const peak = computed(() => peakHour(props.usage.report.hourly));
const favorite = computed(() => favoriteAgent(props.usage.report.by_agent));
const activitySeries = computed(() => {
  const report = props.usage.report;
  if (report.daily.length === 0) return [];
  const daily = new Map(report.daily.map(day => [day.date, day.tokens]));
  const first = new Date(report.since.slice(0, 10) + "T00:00:00Z").getTime();
  const last = new Date(today + "T00:00:00Z").getTime();
  const series: { bucket: string; values: { tokens: number } }[] = [];
  for (let day = first; day <= last; day += 86_400_000) {
    const date = new Date(day).toISOString().slice(0, 10);
    series.push({ bucket: date + "T00:00:00", values: { tokens: daily.get(date) ?? 0 } });
  }
  return series;
});
const ACTIVITY_LINES = [{ id: "tokens", label: "Tokens", color: "var(--accent)" }];
</script>

<template>
<section class="usage-details" :aria-label="`Usage for ${username}`">
<h3>Usage for {{ username }}</h3>
<p v-if="yearFailed" class="muted">Could not load annual activity.</p>

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
          <LineChart v-else :series="activitySeries" :lines="ACTIVITY_LINES" bucket="day" label="Token usage" fill :loading="loading" />

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
            <SegmentedControl v-model="groupBy" :options="GROUP_OPTIONS" label="Group by" aria-label="Group usage by" />
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


</section>
</template>
<style scoped>
.usage-details { min-width: 0; overflow-wrap: anywhere; }
.usage-view {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.head {
  align-items: last baseline;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
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
  align-items: last baseline;
  min-width: 0;
  max-width: 100%;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.ranges > .segmented-control {
  flex: 1 1 auto;
}
.ranges > .export {
  flex: 0 0 auto;
}
@media (max-width: 767px) {
  .ranges { width: 100%; flex-wrap: nowrap; }
}
.panel {
  margin-top: 12px;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.panel-head {
  align-items: last baseline;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px 12px;
  margin-bottom: 12px;
}
.panel-head .small {
  margin: 0;
}
.activity :deep(.chart button.chip) {
  padding: 5px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--text);
  cursor: pointer;
  font-size: 0.8em;
}
.activity :deep(.chart button.chip:focus-visible) {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
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
