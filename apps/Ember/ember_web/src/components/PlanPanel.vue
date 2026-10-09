<script setup lang="ts">
import type { TurnPlan } from "../api/types";

defineProps<{ plans: TurnPlan[] }>();
const labels = { pending: "Pending", in_progress: "In progress", done: "Done" };
const marks = { pending: "○", in_progress: "◐", done: "✓" };
</script>

<template>
  <section v-for="plan in plans" :key="plan.agent_id ?? ''" class="plan" aria-label="Task plan">
    <h4>Plan <span v-if="plan.agent_label || plan.agent_id">· {{ plan.agent_label || plan.agent_id }}</span></h4>
    <ol>
      <li v-for="(item, index) in plan.items" :key="index" :class="item.status">
        <span aria-hidden="true">{{ marks[item.status] }}</span>
        <span class="text">{{ item.text }}</span>
        <span class="status">{{ labels[item.status] }}</span>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.plan { padding: 12px 14px; margin-bottom: 12px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface); }
h4 { margin: 0 0 8px; font-size: 0.9em; font-weight: 600; }
h4 span, .status { color: var(--muted); }
ol { margin: 0; padding: 0; list-style: none; }
li { display: flex; align-items: baseline; gap: 8px; padding: 3px 0; }
.text { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.status { font-size: 0.8em; white-space: nowrap; }
.in_progress > :first-child { color: var(--accent); }
.done > :first-child { color: var(--success); }
</style>
