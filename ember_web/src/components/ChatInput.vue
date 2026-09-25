<script setup lang="ts">
import { nextTick, ref } from "vue";

// busy: a turn is running - Send becomes Stop.
const props = defineProps<{ busy: boolean }>();
const emit = defineEmits<{ send: [question: string]; stop: [] }>();

const draft = ref("");
const textarea = ref<HTMLTextAreaElement | null>(null);

/** Grow with the content; CSS max-height caps it, then it scrolls. */
function autoGrow(): void {
  const el = textarea.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${el.scrollHeight}px`;
}

function submit(): void {
  const question = draft.value.trim();
  if (!question || props.busy) return;
  emit("send", question);
  draft.value = "";
  void nextTick(autoGrow);
}

/** Enter sends, Shift+Enter is a newline. isComposing: never send while an
 * IME (Japanese/Chinese input) is still composing a character. */
function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submit();
  }
}
</script>

<template>
  <form class="composer" @submit.prevent="submit">
    <div class="box">
      <textarea
        ref="textarea"
        v-model="draft"
        rows="1"
        placeholder="Ask something"
        @input="autoGrow"
        @keydown="onKeydown"
      />
      <button v-if="busy" type="button" class="round stop" title="Stop" @click="emit('stop')">
        <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
          <rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor" />
        </svg>
      </button>
      <button v-else type="submit" class="round send" title="Send" :disabled="!draft.trim()">
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <path
            d="M12 19V5M5 12l7-7 7 7"
            fill="none"
            stroke="currentColor"
            stroke-width="2.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </button>
    </div>
  </form>
</template>

<style scoped>
.composer {
  max-width: 820px;
  width: 100%;
  margin: 0 auto;
  padding: 8px 16px 16px;
}
.box {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 8px 8px 8px 16px;
  border: 1px solid var(--border);
  border-radius: 22px;
  background: var(--surface);
}
.box:focus-within {
  border-color: var(--accent);
}
textarea {
  flex: 1;
  max-height: calc(1.55em * 8); /* about 8 lines, then it scrolls */
  padding: 6px 0;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
}
.round {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border: none;
  border-radius: 50%;
  cursor: pointer;
  color: var(--accent-contrast);
  background: var(--accent);
}
.round:disabled {
  cursor: default;
  opacity: 0.35;
}
.stop {
  color: var(--bg);
  background: var(--text);
}
</style>
