<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import type { GuiTabsSectionSpec } from "../api/CapabilityPagesClient";
import type { ToolInfo, ToolRunResult } from "../api/types";
import GuiFormSection from "./GuiFormSection.vue";

/** Several form sections shown one at a time. The tab bar follows the ARIA
 * tabs pattern (roving tabindex; arrows, Home and End). Every tab you have
 * opened stays alive in <KeepAlive>, so it keeps its controls and result. */
const props = defineProps<{
  section: GuiTabsSectionSpec;
  tools: Record<string, ToolInfo>;
  runTool: (name: string, args: Record<string, unknown>) => Promise<ToolRunResult>;
}>();

const active = ref(0);
const buttons = ref<HTMLButtonElement[]>([]);
const current = computed(() => props.section.tabs[active.value]!);
const currentTool = computed(() => props.tools[current.value.tool]);

const tabId = (index: number) => `${props.section.id}-tab-${index}`;
const panelId = `${props.section.id}-panel`;

function select(index: number, focus = false): void {
  active.value = index;
  if (focus) void nextTick(() => buttons.value[index]?.focus());
}

function onKeydown(event: KeyboardEvent): void {
  const last = props.section.tabs.length - 1;
  const next: Record<string, number> = {
    ArrowRight: active.value === last ? 0 : active.value + 1,
    ArrowLeft: active.value === 0 ? last : active.value - 1,
    Home: 0,
    End: last,
  };
  const target = next[event.key];
  if (target === undefined) return;
  event.preventDefault();
  select(target, true);
}
</script>

<template>
  <section class="tabs">
    <div class="tablist" role="tablist" aria-label="Page sections" @keydown="onKeydown">
      <button
        v-for="(tab, i) in section.tabs"
        :id="tabId(i)"
        :key="tab.id"
        ref="buttons"
        type="button"
        role="tab"
        data-test="tab"
        :class="['tab', { active: i === active }]"
        :aria-selected="i === active"
        :aria-controls="panelId"
        :tabindex="i === active ? 0 : -1"
        @click="select(i)"
      >
        {{ tab.title }}
      </button>
    </div>
    <div :id="panelId" class="panel" role="tabpanel" :aria-labelledby="tabId(active)">
      <p v-if="!currentTool" class="error">The tool {{ current.tool }} is not available right now.</p>
      <KeepAlive>
        <GuiFormSection v-if="currentTool" :key="current.id" :section="current" :tool="currentTool" :run-tool="runTool" embedded />
      </KeepAlive>
    </div>
  </section>
</template>

<style scoped>
.tabs {
  margin-bottom: 12px;
}
/* Many tabs on a narrow screen scroll sideways instead of wrapping. */
.tablist {
  display: flex;
  gap: 4px;
  padding: 4px;
  margin-bottom: 14px;
  overflow-x: auto;
  border-radius: 12px;
  background: var(--surface);
}
.tab {
  flex: 1 0 auto;
  padding: 7px 14px;
  border: none;
  border-radius: 9px;
  cursor: pointer;
  font: inherit;
  white-space: nowrap;
  color: var(--muted);
  background: transparent;
}
.tab.active {
  font-weight: 600;
  color: var(--text);
  background: var(--bg);
  box-shadow: 0 0 0 1px var(--border);
}
.tab:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
.error {
  color: var(--danger);
}
</style>
