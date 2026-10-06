<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";
import { copyText } from "../utils/clipboard";

const FEEDBACK_MS = 1500;

const props = defineProps<{ text: string; label?: string }>();

const state = ref<"idle" | "copied" | "failed">("idle");
let timer: ReturnType<typeof setTimeout> | null = null;

async function copy(): Promise<void> {
  state.value = (await copyText(props.text)) ? "copied" : "failed";
  if (timer !== null) clearTimeout(timer);
  timer = setTimeout(() => (state.value = "idle"), FEEDBACK_MS);
}

onBeforeUnmount(() => {
  if (timer !== null) clearTimeout(timer);
});
</script>

<template>
  <button
    type="button"
    class="copy"
    :class="state"
    :title="label ?? 'Copy'"
    :aria-label="label ?? 'Copy'"
    @click="copy"
  >
    <svg v-if="state === 'idle'" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.8" />
      <path d="M5 15V6a2 2 0 0 1 2-2h9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
    </svg>
    <span v-else>{{ state === "copied" ? "Copied" : "Copy failed" }}</span>
  </button>
</template>

<style scoped>
.copy {
  display: inline-flex;
  align-items: center;
  padding: 2px 6px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.75em;
  color: var(--muted);
  background: transparent;
}
.copy:hover {
  color: var(--text);
  background: var(--surface);
}
.copy.failed {
  color: var(--danger);
}
</style>
