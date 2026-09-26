<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { CommandInfo } from "../api/CommandsClient";

// busy: a turn is running - Send becomes Stop. commands: slash commands to
// suggest while "/..." is being typed (empty without tools.use).
const props = withDefaults(defineProps<{ busy: boolean; commands?: CommandInfo[] }>(), { commands: () => [] });
const emit = defineEmits<{ send: [question: string]; stop: [] }>();

const draft = ref("");
const textarea = ref<HTMLTextAreaElement | null>(null);

const MAX_SUGGESTIONS = 8;

interface Suggestion {
  text: string;
  description: string;
}

/** Commands matching what's typed, while still on "/<capability> <command>"
 * (suggestions stop once parameters are being typed). */
const suggestions = computed<Suggestion[]>(() => {
  const typed = draft.value;
  if (!props.commands.length || !/^\/\S*( \S*)?$/.test(typed)) return [];
  const needle = typed.toLowerCase();
  const all: Suggestion[] = [
    { text: "/help", description: "Every capability and its commands" },
    ...[...new Set(props.commands.map((c) => c.capability))].map((cap) => ({
      text: `/${cap} help`,
      description: `How to use ${cap}`,
    })),
    ...props.commands.map((c) => ({ text: `/${c.capability} ${c.name}`, description: c.description })),
  ];
  return all.filter((s) => s.text.toLowerCase().startsWith(needle) && s.text !== typed).slice(0, MAX_SUGGESTIONS);
});
const highlighted = ref(0);
watch(suggestions, () => (highlighted.value = 0));

function complete(suggestion: Suggestion): void {
  draft.value = `${suggestion.text} `;
  void nextTick(() => {
    textarea.value?.focus();
    autoGrow();
  });
}

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
  const open = suggestions.value.length > 0;
  if (open && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
    event.preventDefault();
    const step = event.key === "ArrowDown" ? 1 : -1;
    highlighted.value = (highlighted.value + step + suggestions.value.length) % suggestions.value.length;
    return;
  }
  if (open && event.key === "Tab") {
    event.preventDefault();
    complete(suggestions.value[highlighted.value]!);
    return;
  }
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submit();
  }
}
</script>

<template>
  <form class="composer" @submit.prevent="submit">
    <ul v-if="suggestions.length" class="suggestions" role="listbox" aria-label="Commands">
      <li
        v-for="(s, i) in suggestions"
        :key="s.text"
        role="option"
        :aria-selected="i === highlighted"
        :class="{ active: i === highlighted }"
        @mousedown.prevent="complete(s)"
      >
        <code>{{ s.text }}</code>
        <span>{{ s.description }}</span>
      </li>
      <li class="hint" aria-hidden="true">Tab completes · Enter runs</li>
    </ul>
    <div class="box">
      <textarea
        ref="textarea"
        v-model="draft"
        rows="1"
        :placeholder="commands.length ? 'Ask something, or / for commands' : 'Ask something'"
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
  position: relative;
  max-width: 820px;
  width: 100%;
  margin: 0 auto;
  padding: 8px 16px 16px;
}
.suggestions {
  position: absolute;
  right: 16px;
  bottom: calc(100% - 4px);
  left: 16px;
  z-index: 10;
  max-height: 280px;
  margin: 0;
  padding: 4px;
  overflow-y: auto;
  list-style: none;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.15);
}
.suggestions li {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 10px;
  padding: 6px 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.9em;
}
.suggestions li.active {
  background: var(--bg);
}
.suggestions code {
  font-family: var(--mono);
}
.suggestions span {
  color: var(--muted);
}
.suggestions .hint {
  cursor: default;
  font-size: 0.75em;
  color: var(--muted);
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
