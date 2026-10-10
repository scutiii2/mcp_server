<script setup lang="ts">
import { computed } from "vue";
import { titleCase } from "../../../utils/emberlings";

/** A tier's name in its colour, with a small square marker. The name is always
 * written, so the colour is never the only signal. */
const props = defineProps<{ tierId: string }>();
const label = computed(() => titleCase(props.tierId));
</script>

<template>
  <span class="em-tier" :style="{ '--tier': `var(--em-tier-${tierId}, var(--em-tier-normal))` }">{{ label }}</span>
</template>

<style scoped>
.em-tier {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border: 1px solid var(--tier);
  border-radius: var(--em-radius);
  color: var(--tier);
  background: var(--em-bg);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.em-tier::before {
  content: "";
  width: 5px;
  height: 5px;
  background: currentColor;
}
</style>
