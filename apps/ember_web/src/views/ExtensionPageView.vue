<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { extensionsClient, type ExtensionInfo } from "../api/ExtensionsClient";
import { McpServerClient } from "../api/McpServerClient";
import type { ToolInfo, ToolRunResult } from "../api/types";
import ToolCard from "../components/ToolCard.vue";
import ToolRunModal from "../components/ToolRunModal.vue";
import { errorMessage } from "../utils/errors";
import { safeWebUrl } from "../utils/webUrl";

/** One extension on its own page: what it is, its web app (when it names one)
 * and its tools as rows that open the same run form as the Capabilities page.
 * Built from what mcp_server reports; an extension ships nothing for it. */
const route = useRoute();
const server = new McpServerClient();

const id = computed(() => String(route.params.id ?? ""));
const loading = ref(true);
const problem = ref("");
const extension = ref<ExtensionInfo | null>(null);
const tools = ref<ToolInfo[]>([]);

// The tool whose modal is open; its last result stays until re-run or closed.
const openTool = ref<string | null>(null);
const running = ref(false);
const result = ref<ToolRunResult | null>(null);
const selectedTool = computed(() => tools.value.find((t) => t.name === openTool.value) ?? null);
const webUrl = computed(() => safeWebUrl(extension.value?.web_url));

// A load for an extension the page has since left must not overwrite the newer one.
let current = 0;

async function load(): Promise<void> {
  const seq = ++current;
  const wanted = id.value;
  loading.value = true;
  problem.value = "";
  extension.value = null;
  tools.value = [];
  openTool.value = null;
  try {
    const found = (await extensionsClient.list()).find((e) => e.id === wanted);
    if (seq !== current) return;
    if (!found) {
      problem.value = `Unknown extension '${wanted}'.`;
      return;
    }
    // A failed extension has no tools to list.
    const listed = found.status === "connected" ? await server.listTools() : [];
    if (seq !== current) return;
    extension.value = found;
    const own = new Set(found.tools);
    tools.value = listed.filter((t) => own.has(t.name)).sort((a, b) => a.title.localeCompare(b.title));
  } catch (err) {
    if (seq === current) problem.value = errorMessage(err);
  } finally {
    if (seq === current) loading.value = false;
  }
}

function openToolModal(name: string): void {
  openTool.value = name;
  result.value = null;
}

async function run(name: string, args: Record<string, unknown>): Promise<void> {
  running.value = true;
  result.value = null;
  try {
    const outcome = await server.runTool(name, args);
    // The modal was closed (or another tool opened) while it ran: drop the result.
    if (openTool.value === name) result.value = outcome;
  } catch (err) {
    // Transport/protocol failure - shown the same way as a tool-side error.
    if (openTool.value === name) result.value = { text: String(err), isError: true };
  } finally {
    running.value = false;
  }
}

onMounted(load);
watch(id, load);
</script>

<template>
  <div class="page">
    <p><RouterLink to="/capabilities">← Capabilities</RouterLink></p>
    <p v-if="loading" class="muted">Loading…</p>
    <p v-else-if="problem" class="error" role="alert">{{ problem }}</p>
    <template v-else-if="extension">
      <h2>{{ extension.label }}</h2>
      <code class="name">{{ extension.id }}</code>
      <p v-if="extension.description" class="muted">{{ extension.description }}</p>
      <p v-if="webUrl">
        <a :href="webUrl" target="_blank" rel="noopener noreferrer">Open app</a>
      </p>
      <p v-if="extension.status !== 'connected'" class="error">
        Not connected{{ extension.error ? `: ${extension.error}` : "" }}
      </p>
      <p v-else-if="tools.length === 0" class="muted">No tools.</p>
      <ul v-else class="cards">
        <ToolCard v-for="t in tools" :key="t.name" :tool="t" @open="openToolModal(t.name)" />
      </ul>
    </template>

    <ToolRunModal
      :tool="selectedTool"
      :running="running"
      :result="result"
      @close="openTool = null"
      @run="(args) => selectedTool && run(selectedTool.name, args)"
    />
  </div>
</template>

<style scoped>
.page {
  max-width: 760px;
  margin: 0 auto;
  padding: 16px;
}
.muted {
  color: var(--muted);
}
.error {
  color: var(--danger);
}
.cards {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}
</style>
