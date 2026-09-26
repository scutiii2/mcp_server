<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import type { ChatMessage } from "../api/types";
import MarkdownContent from "./MarkdownContent.vue";

const props = defineProps<{
  messages: ChatMessage[];
  streaming: string;
  activity: string;
  busy: boolean;
}>();

// Within this many px of the bottom counts as "following along".
const STICK_THRESHOLD_PX = 80;

const scroller = ref<HTMLElement | null>(null);
// Follow new content only while the user is at the bottom; scrolling up to
// read something stops it, scrolling back down resumes it.
const stickToBottom = ref(true);

function onScroll(): void {
  const el = scroller.value;
  if (!el) return;
  stickToBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD_PX;
}

async function scrollToBottomIfSticking(): Promise<void> {
  if (!stickToBottom.value) return;
  await nextTick();
  const el = scroller.value;
  if (el) el.scrollTop = el.scrollHeight;
}

watch(
  () => props.messages.length,
  () => {
    // Sending a question always jumps back to the bottom.
    if (props.messages.at(-1)?.role === "user") stickToBottom.value = true;
    void scrollToBottomIfSticking();
  },
);
watch(
  () => [props.streaming, props.activity],
  () => void scrollToBottomIfSticking(),
);
</script>

<template>
  <div ref="scroller" class="scroller" @scroll.passive="onScroll">
    <div class="column">
      <p v-if="messages.length === 0 && !busy" class="empty">Ask ember anything</p>

      <template v-for="(m, i) in messages" :key="i">
        <!-- Raw messages a summary or clear replaced: kept for reading, never
             sent to the agent again. -->
        <details v-if="m.kind === 'log_attachment'" class="log">
          <summary>Earlier messages (not sent to the agent)</summary>
          <pre>{{ m.content }}</pre>
        </details>
        <section v-else-if="m.kind === 'summary'" class="summary">
          <h4>Summary of the earlier conversation</h4>
          <MarkdownContent :text="m.content" />
        </section>
        <div v-else-if="m.kind === 'command' && m.role === 'user'" class="user-bubble command">{{ m.content }}</div>
        <MarkdownContent v-else-if="m.kind === 'command'" class="assistant command-result" :text="m.content" />
        <!-- Only model output is rendered as markdown; the user's own text stays literal. -->
        <div v-else-if="m.role === 'user'" class="user-bubble">{{ m.content }}</div>
        <div v-else class="assistant">
          <MarkdownContent :text="m.content" />
          <p v-if="m.model || m.total_tokens" class="meta">
            {{ [m.model, m.total_tokens ? `${m.total_tokens.toLocaleString()} tokens` : ""].filter(Boolean).join(" · ") }}
          </p>
        </div>
      </template>

      <div v-if="busy" class="assistant live">
        <span v-if="activity" class="activity"><span class="dot" />{{ activity }}</span>
        <MarkdownContent v-if="streaming" :text="streaming" />
        <span v-else-if="!activity" class="activity"><span class="dot" />thinking ...</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scroller {
  overflow-y: auto;
}
.column {
  max-width: 820px;
  margin: 0 auto;
  padding: 24px 16px 8px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.empty {
  margin-top: 25vh;
  text-align: center;
  font-size: 1.4em;
  color: var(--muted);
}
.user-bubble {
  align-self: flex-end;
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 18px 18px 4px 18px;
  background: var(--user-bubble);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.assistant {
  overflow-wrap: anywhere;
}
.meta {
  margin: 4px 0 0;
  font-size: 0.75em;
  color: var(--muted);
}
.command {
  font-family: var(--mono);
  font-size: 0.9em;
}
.command-result {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
}
.summary {
  padding: 10px 14px;
  border-left: 3px solid var(--accent);
  border-radius: 6px;
  background: var(--surface);
}
.summary h4 {
  margin: 0 0 6px;
  font-size: 0.85em;
  color: var(--muted);
}
.log {
  font-size: 0.85em;
  color: var(--muted);
}
.log summary {
  cursor: pointer;
}
.log pre {
  max-height: 360px;
  margin: 8px 0 0;
  padding: 10px;
  overflow: auto;
  border-radius: 8px;
  white-space: pre-wrap;
  font-family: var(--mono);
  background: var(--code-bg);
}
.live {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.activity {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 3px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 0.85em;
  color: var(--muted);
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
  50% {
    opacity: 0.3;
  }
}
</style>
