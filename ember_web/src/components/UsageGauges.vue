<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { usageClient, type MyUsage } from "../api/UsageClient";
import { formatUtc } from "../utils/errors";
import { compactNumber, usagePercent } from "../utils/usageFormat";

// The 6-hour and weekly token limits, small, so they stay in view while
// chatting. Only windows that have a limit are shown. Refreshed when an answer
// ends (`busy` goes false); a failed read just leaves the old numbers, as the
// Usage page is where errors belong.
const props = defineProps<{ busy: boolean }>();

const usage = ref<MyUsage | null>(null);
let seq = 0;

async function load(): Promise<void> {
  const mine = (seq += 1);
  try {
    const result = await usageClient.mine(1);
    if (mine === seq) usage.value = result;
  } catch {
    // keep what is shown
  }
}

const gauges = computed(() => {
  const u = usage.value;
  if (!u) return [];
  return [
    { key: "6 h", title: "Last 6 hours", window: u.six_hour },
    { key: "Week", title: "Last 7 days", window: u.weekly },
  ].filter((g) => g.window.limit > 0);
});

function hint(g: (typeof gauges.value)[number]): string {
  const w = g.window;
  const used = `${w.used.toLocaleString()} of ${w.limit.toLocaleString()} tokens`;
  return w.reset_at && w.used ? `${g.title}: ${used}. Oldest tokens stop counting at ${formatUtc(w.reset_at)}.` : `${g.title}: ${used}.`;
}

onMounted(load);
watch(
  () => props.busy,
  (busy) => {
    if (!busy) void load();
  },
);
</script>

<template>
  <div v-if="gauges.length" class="gauges" aria-label="Token limits">
    <div v-for="g in gauges" :key="g.key" class="gauge" :title="hint(g)">
      <div class="head">
        <span>{{ g.key }}</span>
        <span>{{ compactNumber(g.window.used) }} / {{ compactNumber(g.window.limit) }}</span>
      </div>
      <div
        class="bar"
        role="progressbar"
        :aria-label="g.title"
        :aria-valuenow="usagePercent(g.window)"
        aria-valuemin="0"
        aria-valuemax="100"
      >
        <span :class="{ full: usagePercent(g.window) >= 90 }" :style="{ width: `${usagePercent(g.window)}%` }" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.gauges {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 8px 0;
  border-top: 1px solid var(--border);
}
.head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 3px;
  font-size: 0.75em;
  color: var(--muted);
}
.bar {
  height: 5px;
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
</style>
