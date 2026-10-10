<script setup lang="ts">
import { computed } from "vue";

/** The countdown ring: a copper arc that shrinks with the time left, around the
 * seconds as a number. At zero the arc turns slate. The number is always shown. */
const props = defineProps<{ remaining: number; total: number }>();
const fraction = computed(() => (props.total > 0 ? Math.min(1, Math.max(0, props.remaining / props.total)) : 0));
const seconds = computed(() => Math.max(0, Math.ceil(props.remaining)));
const expired = computed(() => props.remaining <= 0);
const arc = computed(() => `conic-gradient(var(--em-accent) 0 ${fraction.value * 100}%, var(--em-divider) ${fraction.value * 100}% 100%)`);
</script>

<template>
  <div class="em-ring" :class="{ expired }" :style="{ background: expired ? undefined : arc }" role="timer" :aria-label="`${seconds} seconds left`">
    <strong class="em-pixel em-num">{{ seconds }}s</strong>
  </div>
</template>

<style scoped>
.em-ring {
  position: relative;
  display: grid;
  width: 88px;
  height: 88px;
  place-items: center;
  border-radius: var(--radius-full);
}
.em-ring.expired {
  background: var(--em-disabled-border);
}
.em-ring::before {
  content: "";
  position: absolute;
  inset: 6px;
  border-radius: var(--radius-full);
  background: var(--em-panel);
}
strong {
  position: relative;
  font-size: 24px;
}
@media (max-width: 700px) {
  .em-ring {
    width: 80px;
    height: 80px;
  }
}
</style>
