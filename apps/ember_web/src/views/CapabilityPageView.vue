<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { capabilityPagesClient, type GuiPageSpec } from "../api/CapabilityPagesClient";
import { commandsClient } from "../api/CommandsClient";
import { ApiError } from "../api/http";
import { McpServerClient } from "../api/McpServerClient";
import type { ToolInfo } from "../api/types";
import GuiFormSection from "../components/GuiFormSection.vue";
import { errorMessage } from "../utils/errors";
import { GuiPageError, parseGuiPage } from "../utils/guiPage";

/** A capability's own page (mcp_server's gui/page.json): a title, notes and
 * one form per tool section. Nothing here is specific to one capability. */
const route = useRoute();
const server = new McpServerClient();

const name = computed(() => String(route.params.name ?? ""));
const loading = ref(true);
const problem = ref("");
const page = ref<GuiPageSpec | null>(null);
const label = ref("");
const tools = ref<Record<string, ToolInfo>>({});

// Only the latest load may write state; a slower earlier one is dropped.
let current = 0;

async function load(): Promise<void> {
  const seq = ++current;
  loading.value = true;
  problem.value = "";
  page.value = null;
  tools.value = {};
  try {
    const requested = name.value;
    const capability = (await commandsClient.capabilities()).find((c) => c.name === requested);
    if (seq !== current) return;
    if (!capability) {
      problem.value = `Unknown capability '${requested}'.`;
      return;
    }
    label.value = capability.label ?? capability.name;
    if (!capability.enabled) {
      problem.value = `${label.value} is turned off.`;
      return;
    }
    const [raw, allTools] = await Promise.all([capabilityPagesClient.get(requested), server.listTools()]);
    if (seq !== current) return;
    page.value = parseGuiPage(raw, capability.tools);
    tools.value = Object.fromEntries(allTools.map((t) => [t.name, t]));
  } catch (err) {
    if (seq !== current) return;
    if (err instanceof GuiPageError) problem.value = `This page's layout is invalid: ${err.message}`;
    else if (err instanceof ApiError && err.status === 404) problem.value = `${label.value || name.value} has no page.`;
    else problem.value = errorMessage(err);
  } finally {
    if (seq === current) loading.value = false;
  }
}

const runTool = (tool: string, args: Record<string, unknown>) => server.runTool(tool, args);

onMounted(load);
watch(name, load);
</script>

<template>
  <div class="scroll">
    <div class="page">
      <p><RouterLink to="/capabilities">← Capabilities</RouterLink></p>
      <p v-if="loading" class="muted">Loading…</p>
      <p v-else-if="problem" class="error" role="alert">{{ problem }}</p>
      <template v-else-if="page">
        <h2>{{ page.title }}</h2>
        <p v-if="page.description" class="muted">{{ page.description }}</p>
        <template v-for="s in page.sections" :key="s.id">
          <section v-if="s.type === 'text'" class="note">
            <h3 v-if="s.title">{{ s.title }}</h3>
            <p>{{ s.text }}</p>
          </section>
          <GuiFormSection v-else-if="tools[s.tool]" :section="s" :tool="tools[s.tool]" :run-tool="runTool" />
          <p v-else class="error">The tool {{ s.tool }} is not available right now.</p>
        </template>
      </template>
    </div>
  </div>
</template>

<style scoped>
/* The shell gives views no scroll of their own; this one scrolls itself. */
.scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
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
</style>
