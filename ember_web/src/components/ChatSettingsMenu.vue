<script setup lang="ts">
// The chat page's settings behind a gear at the top-right corner: closed on
// every load, closed again by Escape or a click anywhere else.
import { nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef } from "vue";
import { RouterLink } from "vue-router";

defineProps<{
  caveman: boolean;
  askBeforeTools: boolean;
  /** An administrator requires approval before every tool: not changeable. */
  forceToolApproval: boolean;
  chime: boolean;
  /** Tools already allowed for this chat. */
  allowedCount: number;
  enabledExtensions: string[];
  /** Puts a dot on the gear, e.g. while a tool waits for an answer. */
  attention: boolean;
}>();

const emit = defineEmits<{
  "update:caveman": [value: boolean];
  "update:askBeforeTools": [value: boolean];
  "update:chime": [value: boolean];
  "clear-allowed": [];
}>();

const open = ref(false);
const root = useTemplateRef<HTMLElement>("root");
const gearButton = useTemplateRef<HTMLButtonElement>("gearButton");

function checked(event: Event): boolean {
  return (event.target as HTMLInputElement).checked;
}

function onDocumentClick(event: MouseEvent): void {
  if (open.value && root.value && !root.value.contains(event.target as Node)) open.value = false;
}

async function closeWithEscape(): Promise<void> {
  open.value = false;
  await nextTick();
  gearButton.value?.focus();
}

onMounted(() => document.addEventListener("click", onDocumentClick));
onBeforeUnmount(() => document.removeEventListener("click", onDocumentClick));
</script>

<template>
  <div ref="root" class="settings-menu">
    <button
      ref="gearButton"
      type="button"
      class="gear"
      title="Chat settings"
      aria-label="Chat settings"
      aria-haspopup="true"
      :aria-expanded="open"
      @click="open = !open"
    >
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
        <circle cx="12" cy="12" r="3" />
        <path
          d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h0a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h0a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"
        />
      </svg>
      <span v-if="attention" class="dot" aria-hidden="true" />
    </button>

    <div v-if="open" class="panel" role="group" aria-label="Chat settings" @keydown.esc.stop="closeWithEscape">
      <label title="Ask the agent for short, terse answers">
        <input type="checkbox" :checked="caveman" @change="emit('update:caveman', checked($event))" />
        Terse replies
      </label>
      <label
        :title="
          forceToolApproval
            ? 'Your administrator requires approval before every tool'
            : 'Ask you before the agent runs each tool'
        "
      >
        <input
          type="checkbox"
          :checked="askBeforeTools || forceToolApproval"
          :disabled="forceToolApproval"
          @change="emit('update:askBeforeTools', checked($event))"
        />
        Ask before tools
      </label>
      <button
        v-if="askBeforeTools && allowedCount && !forceToolApproval"
        type="button"
        class="allowed"
        title="Ask again about the tools you allowed for this chat"
        @click="emit('clear-allowed')"
      >
        {{ allowedCount }} tool{{ allowedCount === 1 ? "" : "s" }} allowed - reset
      </button>
      <label title="Play a short chime when an answer arrives while this tab is in the background">
        <input type="checkbox" :checked="chime" @change="emit('update:chime', checked($event))" />
        Chime when done
      </label>
      <RouterLink to="/extensions" class="extensions" title="Which extensions' tools the agent may use in your chats">
        Extensions: {{ enabledExtensions.length ? enabledExtensions.join(", ") : "off" }}
      </RouterLink>
    </div>
  </div>
</template>

<style scoped>
.settings-menu {
  position: absolute;
  top: 8px;
  right: 16px;
  z-index: 15;
}
.gear {
  position: relative;
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  color: var(--muted);
  background: var(--bg);
}
.gear:hover,
.gear[aria-expanded="true"] {
  color: var(--text);
  border-color: var(--accent);
}
.gear svg {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.dot {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
}
.panel {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  width: max-content;
  max-width: min(320px, calc(100vw - 32px));
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.25);
}
label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.9em;
  cursor: pointer;
}
label:has(input:disabled) {
  cursor: default;
}
.allowed {
  margin-left: 24px;
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  cursor: pointer;
  font-size: 0.75em;
  color: var(--muted);
  background: transparent;
}
.allowed:hover {
  color: var(--text);
  border-color: var(--accent);
}
.extensions {
  font-size: 0.85em;
  color: var(--muted);
  text-decoration: none;
}
.extensions:hover {
  color: var(--text);
}
</style>
