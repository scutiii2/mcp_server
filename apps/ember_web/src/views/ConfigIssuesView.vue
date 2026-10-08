<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import type { ConfigIssue, ConfigIssueSeverity } from "../api/ConfigIssuesClient";
import "../components/infoPage.css";
import { useConfigIssuesStore } from "../stores/configIssues";

/** Problems in ember_api's config and secret files (port of chat_app's
 * Config issues page). File and key names only, never secret values. The
 * page opens only while there are issues; once a check finds none it
 * leaves for the home page. */

const store = useConfigIssuesStore();
const router = useRouter();

type Filter = "all" | ConfigIssueSeverity;
const filter = ref<Filter>("all");

const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? "" : "s"}`;

const summary = computed(() => {
  const parts = [];
  if (store.errorCount) parts.push(plural(store.errorCount, "error"));
  if (store.warningCount) parts.push(plural(store.warningCount, "warning"));
  return parts.join(" · ");
});

const shown = computed(() => store.issues.filter((i) => filter.value === "all" || i.severity === filter.value));

/** One card per file, the files with errors first. */
const byFile = computed(() => {
  const groups = new Map<string, ConfigIssue[]>();
  for (const issue of shown.value) {
    const list = groups.get(issue.file) ?? [];
    list.push(issue);
    groups.set(issue.file, list);
  }
  const rank = (list: ConfigIssue[]) => (list.some((i) => i.severity === "error") ? 0 : 1);
  return [...groups.entries()]
    .map(([file, items]) => ({
      file,
      items: [...items].sort((a, b) => Number(a.severity === "warning") - Number(b.severity === "warning")),
    }))
    .sort((a, b) => rank(a.items) - rank(b.items));
});

async function check(): Promise<void> {
  await store.refresh();
  if (!store.error && store.issues.length === 0) await router.replace("/");
}
</script>

<template>
  <section class="info-page">
    <div class="column page-column">
      <div class="head">
        <h2 class="page-title">Config issues</h2>
        <button type="button" class="chip" :disabled="store.loading" @click="check">Check again</button>
      </div>
      <p class="muted intro page-description">
        Problems in <code>ember_api/configs</code> and <code>ember_api/secrets</code>. Secret files are re-read on
        every check; changes to <code>config_app.json</code> take effect once ember_api restarts.
      </p>

      <p v-if="store.error" class="error">{{ store.error }}</p>

      <template v-if="store.issues.length">
        <div class="banner" :class="store.errorCount ? 'errors' : 'warnings'" role="status">
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <path d="M12 9v4M12 17h.01" />
          </svg>
          <strong>{{ summary }}</strong>
        </div>

        <div class="filters" role="group" aria-label="Filter by level">
          <button type="button" class="chip" :class="{ active: filter === 'all' }" @click="filter = 'all'">
            All {{ store.issues.length }}
          </button>
          <button
            type="button"
            class="chip"
            :class="{ active: filter === 'error' }"
            :disabled="!store.errorCount"
            @click="filter = 'error'"
          >
            Errors {{ store.errorCount }}
          </button>
          <button
            type="button"
            class="chip"
            :class="{ active: filter === 'warning' }"
            :disabled="!store.warningCount"
            @click="filter = 'warning'"
          >
            Warnings {{ store.warningCount }}
          </button>
        </div>

        <div v-for="g in byFile" :key="g.file" class="card file">
          <div class="file-head">
            <code>{{ g.file }}</code>
            <span class="muted">{{ plural(g.items.length, "problem") }}</span>
          </div>
          <div v-for="(i, n) in g.items" :key="n" class="row">
            <span class="level" :class="i.severity">{{ i.severity }}</span>
            <code class="key">{{ i.key }}</code>
            <span class="message">{{ i.message }}</span>
          </div>
        </div>
      </template>
      <p v-else-if="store.loading" class="muted">checking ...</p>
    </div>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.banner {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding: 10px 14px;
  border: 1px solid var(--tone);
  border-radius: var(--radius-lg);
  color: var(--tone);
  background: color-mix(in srgb, var(--tone) 10%, var(--bg));
}
.banner svg {
  flex-shrink: 0;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.banner.errors,
.level.error {
  --tone: var(--status-failed);
}
.banner.warnings,
.level.warning {
  --tone: var(--warning);
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}
.file {
  padding: 0;
  overflow: hidden;
}
.file-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 0.85em;
}
.row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 9px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 0.9em;
}
.row:last-child {
  border-bottom: none;
}
.level {
  flex-shrink: 0;
  min-width: 56px;
  padding: 1px 8px;
  border-radius: var(--radius-full);
  font-size: 0.78em;
  text-align: center;
  color: var(--tone);
  background: color-mix(in srgb, var(--tone) 12%, var(--bg));
}
.key {
  flex-shrink: 0;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: var(--code-bg);
}
.message {
  min-width: 0;
  overflow-wrap: anywhere;
}
@media (max-width: 600px) {
  .row {
    flex-wrap: wrap;
  }
}
</style>
