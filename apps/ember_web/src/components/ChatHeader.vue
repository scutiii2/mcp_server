<script setup lang="ts">
import { computed, nextTick, ref, useTemplateRef } from "vue";
import type { MenuItem } from "../utils/chatMenu";
import { useAuthStore } from "../stores/auth";
import ActionButton from "./ActionButton.vue";
import EntryAgentTag from "./EntryAgentTag.vue";
import PopupMenu from "./PopupMenu.vue";

/** The bar above a chat: its title, who it talks to, how full the agent's
 * memory is, and the actions on the chat. Export and Share are icon buttons;
 * Summarize and Clear (they change what the agent remembers) sit in a menu and
 * are off while an answer is being written (`locked`). The actions show once
 * the chat has messages. */
const props = defineProps<{
  title: string;
  hasMessages: boolean;
  /** Share of the agent's context in use, or null before an answer. */
  contextPercent: number | null;
  locked: boolean;
}>();

const emit = defineEmits<{ export: []; share: []; summarize: []; clear: [] }>();

const auth = useAuthStore();

const MENU_WIDTH = 210;

const menuAt = ref<{ x: number; y: number } | null>(null);
const more = useTemplateRef<InstanceType<typeof ActionButton>>("more");
const moreButton = (): HTMLElement | null => (more.value?.$el as HTMLElement | undefined) ?? null;

const items = computed<MenuItem[]>(() => [
  { id: "summarize", label: "Summarize", disabled: props.locked },
  { id: "clear", label: "Clear", disabled: props.locked },
]);

// A press on the "..." button while the menu is open closes it: the button keeps
// its pointerdown from the menu, which would close it first and let the click reopen it.
function toggleMenu(): void {
  if (menuAt.value) {
    void closeMenu();
    return;
  }
  const box = moreButton()?.getBoundingClientRect();
  menuAt.value = { x: (box?.right ?? MENU_WIDTH) - MENU_WIDTH, y: (box?.bottom ?? 0) + 4 };
}

/** Esc, a press outside or Tab: focus goes back to the button. */
async function closeMenu(): Promise<void> {
  menuAt.value = null;
  await nextTick();
  moreButton()?.focus();
}

function choose(id: string): void {
  menuAt.value = null; // a choice opens a dialog, which takes focus
  if (id === "summarize") emit("summarize");
  else if (id === "clear") emit("clear");
}
</script>

<template>
  <header class="chat-header">
    <h2 class="title" :title="title">{{ title }}</h2>
    <EntryAgentTag />
    <span class="spacer" />
    <span
      v-if="contextPercent !== null"
      :class="['context', { high: contextPercent >= 50 }]"
      title="How full the agent's memory of this chat is. At 60% the chat is summarized automatically."
    >
      Context
      <span class="meter" role="progressbar" aria-label="Context used" :aria-valuenow="contextPercent" aria-valuemin="0" aria-valuemax="100">
        <i :style="{ width: `${contextPercent}%` }" />
      </span>
      {{ contextPercent }}%
    </span>
    <template v-if="hasMessages">
      <ActionButton icon="export" icon-only title="Download this chat as Markdown" @click="emit('export')">Export</ActionButton>
      <ActionButton v-if="auth.hasPermission('chat.share')" icon="share" icon-only title="Make a read-only link to this chat" @click="emit('share')">Share</ActionButton>
      <ActionButton
        ref="more"
        icon="more"
        icon-only
        class="more"
        title="More chat actions"
        aria-haspopup="menu"
        :aria-expanded="menuAt !== null"
        @pointerdown.stop
        @click.stop="toggleMenu"
      >
        More
      </ActionButton>
    </template>
    <PopupMenu v-if="menuAt" :items="items" :x="menuAt.x" :y="menuAt.y" label="Chat actions" @select="choose" @close="closeMenu" />
  </header>
</template>

<style scoped>
.chat-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 12px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--bg);
}
.title {
  min-width: 0;
  max-width: 40ch;
  margin: 0;
  overflow: hidden;
  font-size: 1em;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.spacer {
  flex: 1;
}
.context {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8em;
  color: var(--muted);
}
.context.high {
  color: var(--danger);
}
.meter {
  width: 44px;
  height: 5px;
  overflow: hidden;
  border-radius: var(--radius-full);
  background: var(--code-bg);
}
.meter i {
  display: block;
  height: 100%;
  background: var(--accent);
}
.high .meter i {
  background: var(--danger);
}
/* Room for the floating chats button on narrow screens. */
@media (max-width: 767px) {
  .chat-header {
    padding-left: 50px;
  }
}
</style>
