<script setup lang="ts">
import { computed } from "vue";
import { useEmberlingsStore } from "../../stores/emberlings";
import { tierStanding, titleCase } from "../../utils/emberlings";

/** A tier's name as a badge; the strongest tiers carry the accent. */
const props = defineProps<{ tierId: string }>();
const store = useEmberlingsStore();
const standing = computed(() => tierStanding(store.catalog?.tiers ?? [], props.tierId));
</script>

<template>
  <span class="tier-badge" :class="standing">{{ titleCase(tierId) }}</span>
</template>

<style scoped>
.tier-badge {
  display: inline-block;
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 0.75em;
  font-weight: 600;
  white-space: nowrap;
  color: var(--muted);
  background: var(--code-bg);
}
.tier-badge.middle {
  border-color: var(--text);
  color: var(--text);
}
.tier-badge.top {
  border-color: var(--accent);
  color: var(--accent-contrast);
  background: var(--accent);
}
</style>
