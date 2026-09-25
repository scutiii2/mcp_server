<script setup lang="ts">
import { computed } from "vue";
import { renderMarkdown } from "../utils/markdown";

const props = defineProps<{ text: string }>();

// Recomputed only when text changes (each streamed token during a turn).
const html = computed(() => renderMarkdown(props.text));
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -- sanitized in renderMarkdown -->
  <div class="markdown" v-html="html" />
</template>

<style scoped>
.markdown > :deep(:first-child) {
  margin-top: 0;
}
.markdown > :deep(:last-child) {
  margin-bottom: 0;
}
.markdown :deep(p) {
  margin: 0.5em 0;
}
.markdown :deep(pre) {
  padding: 12px 14px;
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--code-bg);
}
.markdown :deep(code) {
  font-family: var(--mono);
  font-size: 0.9em;
}
.markdown :deep(:not(pre) > code) {
  padding: 0.1em 0.35em;
  border-radius: 4px;
  background: var(--code-bg);
}
.markdown :deep(table) {
  display: block;
  max-width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
  margin: 0.5em 0;
}
.markdown :deep(th),
.markdown :deep(td) {
  padding: 6px 10px;
  border: 1px solid var(--border);
}
.markdown :deep(th) {
  background: var(--surface);
}
.markdown :deep(ul),
.markdown :deep(ol) {
  padding-left: 1.4em;
}
.markdown :deep(blockquote) {
  margin: 0.5em 0;
  padding-left: 12px;
  border-left: 3px solid var(--border);
  color: var(--muted);
}
</style>
