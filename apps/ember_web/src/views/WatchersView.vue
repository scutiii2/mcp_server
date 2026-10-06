<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { watchersClient, type WatcherInfo } from "../api/WatchersClient";
import CapabilityFocus from "../components/watchers/CapabilityFocus.vue";
import WatcherList from "../components/watchers/WatcherList.vue";
import WatcherTimeline from "../components/watchers/WatcherTimeline.vue";
import "../components/infoPage.css";
import SegmentedControl from "../components/SegmentedControl.vue";
import { errorMessage } from "../utils/errors";
import {
  RANGE_OPTIONS,
  STATUS_COLORS,
  STATUS_ICONS,
  STATUS_LABELS,
  countStatuses,
  formatDuration,
  groupByCapability,
  inOrder,
  intervalOf,
  matching,
  overlaps,
  stableOrder,
  statusOf,
  timeAgo,
  visibleGroups,
  windowOf,
  type WatcherRange,
} from "../utils/watchers";

/** Status of mcp_server's background watchers, every capability's (port of chat_app's Watchers
 * page). Read-only and live: refreshed every 15 s; everything below is derived from the rows
 * already fetched. One timeline lane per capability that opens into one lane per watcher; the
 * list under it follows the same open lanes. `?capability=` narrows the page to one. */

const REFRESH_MS = 15_000;
// Lanes drawn before "Show all"; a capability with a failure is always drawn.
const TOP_LANES = 8;

const route = useRoute();
const router = useRouter();

const watchers = ref<WatcherInfo[]>([]);
const loading = ref(true);
const refreshing = ref(false);
const error = ref("");
const partialErrors = ref<string[]>([]);
const now = ref(Date.now());
const clock = ref(Date.now());
const updatedAt = ref<number | null>(null);

const range = ref<WatcherRange>("24h");
const search = ref("");
const showAll = ref(false);
const expanded = ref(new Set<string>());
// Lane order that holds still across refreshes (see stableOrder).
const order = ref<string[]>([]);
let seeded = false;

const allGroups = computed(() => groupByCapability(watchers.value));
const focusOptions = computed(() =>
  allGroups.value
    .map((g) => ({ name: g.capability, watchers: g.watchers.length, failed: g.counts.failed > 0, running: g.counts.running > 0 }))
    .sort((a, b) => a.name.localeCompare(b.name)),
);
// The address names a capability; one that is not (or no longer) there means "all".
const focus = computed(() => {
  const asked = route.query.capability;
  return typeof asked === "string" && allGroups.value.some((g) => g.capability === asked) ? asked : null;
});

const timeWindow = computed(() => windowOf(range.value, watchers.value, now.value));
const filtered = computed(() =>
  matching(
    watchers.value.filter((w) => overlaps(w, timeWindow.value, now.value)),
    search.value,
  ),
);
const scoped = computed(() => {
  const groups = inOrder(groupByCapability(filtered.value), order.value);
  return focus.value ? groups.filter((g) => g.capability === focus.value) : groups;
});
const shown = computed(() => (focus.value ? scoped.value : visibleGroups(scoped.value, TOP_LANES, showAll.value)));
const hiddenLanes = computed(() => scoped.value.length - shown.value.length);
const canCollapse = computed(() => showAll.value && !focus.value && scoped.value.length > TOP_LANES);

const scopedWatchers = computed(() => scoped.value.flatMap((g) => g.watchers));
const counts = computed(() => countStatuses(scopedWatchers.value));
const failedCapabilities = computed(() => scoped.value.filter((g) => g.counts.failed > 0).length);
const oldestRunning = computed(() => {
  const starts = scopedWatchers.value
    .filter((w) => statusOf(w) === "running")
    .map((w) => intervalOf(w, now.value)?.start)
    .filter((s): s is number => s !== undefined);
  return starts.length ? now.value - Math.min(...starts) : null;
});
const rangeText = computed(() => RANGE_OPTIONS.find((o) => o.value === range.value)?.long ?? "");
const updatedText = computed(() => (updatedAt.value === null ? "" : timeAgo(updatedAt.value, clock.value)));

function setFocus(name: string | null): void {
  void router.replace({ query: { ...route.query, capability: name ?? undefined } });
}

function toggle(capability: string): void {
  const next = new Set(expanded.value);
  if (!next.delete(capability)) next.add(capability);
  expanded.value = next;
}

async function refresh(): Promise<void> {
  refreshing.value = true;
  try {
    const report = await watchersClient.list();
    watchers.value = report.watchers;
    partialErrors.value = report.errors;
    error.value = "";
    updatedAt.value = Date.now();
    const groups = groupByCapability(report.watchers);
    order.value = stableOrder(order.value, groups);
    if (!seeded) {
      // Failing capabilities start open; after that the lanes are the reader's.
      expanded.value = new Set(groups.filter((g) => g.counts.failed > 0).map((g) => g.capability));
      seeded = true;
    }
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    loading.value = false;
    refreshing.value = false;
    now.value = clock.value = Date.now();
  }
}

// Only while the page is shown (it may be kept alive in the background).
let timer: ReturnType<typeof setInterval> | null = null;
let ticker: ReturnType<typeof setInterval> | null = null;
function startTimers(): void {
  stopTimers();
  timer = setInterval(() => void refresh(), REFRESH_MS);
  ticker = setInterval(() => (clock.value = Date.now()), 1000);
}
function stopTimers(): void {
  if (timer !== null) clearInterval(timer);
  if (ticker !== null) clearInterval(ticker);
  timer = ticker = null;
}
onMounted(() => {
  void refresh();
  startTimers();
});
onActivated(startTimers);
onDeactivated(stopTimers);
onUnmounted(stopTimers);
</script>

<template>
  <section class="info-page">
    <div class="column">
      <div class="top">
        <div>
          <h2>Watchers</h2>
          <p class="muted intro">Background jobs mcp_server's capabilities are watching. Recipients are set on the mcp_server side.</p>
        </div>
        <span v-if="updatedText" :class="['live', { stale: !!error }]">
          <span class="pulse" aria-hidden="true" />
          {{ error ? "Not updating" : "Live" }} · updated {{ updatedText }}
        </span>
      </div>

      <p v-if="error" class="error">Could not reach mcp_server: {{ error }}</p>
      <p v-else-if="partialErrors.length" class="error">Some capabilities didn't answer: {{ partialErrors.join("; ") }}</p>

      <div class="toolbar">
        <input v-model="search" type="search" placeholder="Search watchers" aria-label="Search watchers" class="search" />
        <CapabilityFocus v-if="focusOptions.length" :model-value="focus" :options="focusOptions" @update:model-value="setFocus" />
        <SegmentedControl v-model="range" :options="RANGE_OPTIONS" aria-label="Range" />
        <button type="button" class="chip" :disabled="refreshing" @click="refresh">Refresh</button>
      </div>

      <p v-if="loading" class="muted">Loading …</p>
      <p v-else-if="watchers.length === 0" class="muted">No watchers are running.</p>
      <template v-else>
        <div class="tiles">
          <div class="tile">
            <span class="label">Running</span>
            <span class="value" :style="counts.running ? { color: STATUS_COLORS.running } : undefined">{{ counts.running }}</span>
            <span class="sub">{{ oldestRunning === null ? "none right now" : `oldest ${formatDuration(oldestRunning)}` }}</span>
          </div>
          <div class="tile">
            <span class="label">Succeeded</span>
            <span class="value">{{ counts.succeeded }}</span>
            <span class="sub">{{ rangeText }}</span>
          </div>
          <div class="tile">
            <span class="label">Failed</span>
            <span class="value" :style="counts.failed ? { color: STATUS_COLORS.failed } : undefined">{{ counts.failed }}</span>
            <span class="sub">
              {{ counts.failed ? `${failedCapabilities} ${failedCapabilities === 1 ? "capability" : "capabilities"} affected` : "none" }}
            </span>
          </div>
        </div>

        <p v-if="scoped.length === 0" class="muted">No watchers match the filters.</p>
        <template v-else>
          <div class="card">
            <div class="card-head">
              <h3>Timeline</h3>
              <ul class="legend">
                <li v-for="s in (['running', 'succeeded', 'failed'] as const)" :key="s">
                  <span class="swatch" :style="{ background: STATUS_COLORS[s] }" />
                  <span aria-hidden="true">{{ STATUS_ICONS[s] }}</span>
                  {{ STATUS_LABELS[s] }}
                </li>
              </ul>
            </div>
            <WatcherTimeline :groups="shown" :expanded="expanded" :force-open="!!focus" :window="timeWindow" :now="now" @toggle="toggle" />
            <div v-if="hiddenLanes > 0 || canCollapse" class="more">
              <button type="button" class="chip" @click="showAll = !showAll">
                {{ showAll ? `Show top ${TOP_LANES}` : `Show all ${scoped.length} capabilities` }}
              </button>
            </div>
          </div>

          <div class="card list-card">
            <WatcherList :groups="shown" :expanded="expanded" :force-open="!!focus" :now="now" @toggle="toggle" />
          </div>
        </template>
      </template>
    </div>
  </section>
</template>

<style scoped>
.top {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 4px 16px;
}
.live {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  font-size: 0.8em;
  color: var(--muted);
}
.pulse {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--status-running);
}
.live.stale .pulse {
  background: var(--status-failed);
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
  margin: 6px 0 14px;
}
.search {
  flex: 1 1 180px;
  min-width: 0;
  max-width: 280px;
}
.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}
.tile {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 14px;
  border-radius: var(--radius-lg);
  background: var(--code-bg);
}
.tile .label {
  font-size: 0.8em;
  color: var(--muted);
}
.tile .value {
  font-size: 1.6em;
  font-weight: 600;
  line-height: 1.2;
}
.tile .sub {
  font-size: 0.8em;
  color: var(--muted);
}
.card-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 6px 12px;
  margin-bottom: 10px;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: 0.8em;
  color: var(--muted);
}
.legend li {
  display: flex;
  align-items: center;
  gap: 5px;
}
.swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}
.more {
  margin-top: 10px;
  text-align: center;
}
.list-card {
  padding: 0;
  overflow: hidden;
}
</style>
