<script setup lang="ts">
import { computed } from "vue";
import { copyText } from "../utils/clipboard";
import { renderMarkdown } from "../utils/markdown";

const FEEDBACK_MS = 1500;

const props = defineProps<{ text: string }>();

// Recomputed only when text changes (each streamed token during a turn).
const html = computed(() => renderMarkdown(props.text));

/** One delegated handler for every code block's Copy button: the buttons are
 * part of the rendered HTML, which is replaced on each streamed token. */
async function onClick(event: MouseEvent): Promise<void> {
  const button = (event.target as HTMLElement).closest<HTMLButtonElement>("button.code-copy");
  const code = button?.parentElement?.querySelector("pre code, pre");
  if (!button || !code) return;
  const ok = await copyText(code.textContent ?? "");
  button.textContent = ok ? "Copied" : "Copy failed";
  setTimeout(() => {
    if (button.isConnected) button.textContent = "Copy";
  }, FEEDBACK_MS);
}
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -- sanitized in renderMarkdown -->
  <div class="markdown" @click="onClick" v-html="html" />
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
.markdown :deep(.code-block) {
  position: relative;
}
.markdown :deep(.code-copy) {
  position: absolute;
  top: 6px;
  right: 6px;
  padding: 2px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 0.75em;
  color: var(--muted);
  background: var(--surface);
  opacity: 0;
  transition: opacity 0.1s;
}
.markdown :deep(.code-block:hover .code-copy),
.markdown :deep(.code-copy:focus-visible) {
  opacity: 1;
}
.markdown :deep(.code-copy:hover) {
  color: var(--text);
}
@media (hover: none) {
  .markdown :deep(.code-copy) {
    opacity: 1;
  }
}
.markdown :deep(pre) {
  padding: 12px 14px;
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--code-bg);
}
.markdown :deep(code) {
  font-family: var(--mono);
  font-size: 0.9em;
}
.markdown :deep(:not(pre) > code) {
  padding: 0.1em 0.35em;
  border-radius: var(--radius-sm);
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
