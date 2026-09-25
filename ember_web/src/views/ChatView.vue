<script setup lang="ts">
import { storeToRefs } from "pinia";
import { ref } from "vue";
import AgentPicker from "../components/AgentPicker.vue";
import ChatInput from "../components/ChatInput.vue";
import ConversationSidebar from "../components/ConversationSidebar.vue";
import MessageList from "../components/MessageList.vue";
import { useAgentsStore } from "../stores/agents";
import { useChatStore } from "../stores/chat";
import { conversationToMarkdown, downloadText, exportFileName } from "../utils/chatExport";

const chat = useChatStore();
// storeToRefs keeps destructured state reactive; actions come off `chat`.
const { sortedConversations, activeId, active, messages, streaming, activity, busy } = storeToRefs(chat);
const agentsStore = useAgentsStore();

// Narrow screens only: the sidebar is a drawer toggled by the menu button.
const drawerOpen = ref(false);

function onNew(): void {
  chat.newChat();
  drawerOpen.value = false;
}

function exportActive(): void {
  const conversation = active.value;
  if (!conversation) return;
  const agentLabel = agentsStore.agents.find((a) => a.id === conversation.agentId)?.label ?? conversation.agentId ?? null;
  downloadText(
    exportFileName(conversation.title, "md"),
    conversationToMarkdown(conversation, agentLabel),
    "text/markdown",
  );
}

function clearActive(): void {
  const conversation = active.value;
  if (!conversation) return;
  if (confirm(`Clear all messages in "${conversation.title}"? The chat itself stays.`)) chat.clearChat(conversation.id);
}

function onSelect(id: string): void {
  chat.selectChat(id);
  drawerOpen.value = false;
}
</script>

<template>
  <section class="chat-view">
    <ConversationSidebar
      :class="['sidebar', { open: drawerOpen }]"
      :conversations="sortedConversations"
      :active-id="activeId"
      :locked="busy"
      @new="onNew"
      @select="onSelect"
      @delete="chat.deleteChat"
      @rename="chat.renameChat"
      @delete-all="chat.deleteAllChats"
    />
    <div v-if="drawerOpen" class="backdrop" @click="drawerOpen = false" />

    <div class="main">
      <button type="button" class="menu" title="Chats" @click="drawerOpen = true">
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path d="M4 7h16M4 12h16M4 17h16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
        </svg>
      </button>
      <MessageList
        class="messages"
        :messages="messages"
        :streaming="streaming"
        :activity="activity"
        :busy="busy"
      />
      <div class="composer-area">
        <div class="toolbar">
          <AgentPicker :locked="busy" />
          <div v-if="active && messages.length" class="chat-actions">
            <button type="button" title="Download this chat as Markdown" @click="exportActive">Export</button>
            <button type="button" title="Remove all messages from this chat" :disabled="busy" @click="clearActive">
              Clear
            </button>
          </div>
        </div>
        <ChatInput :busy="busy" @send="chat.send" @stop="chat.stop" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.chat-view {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
}
.main {
  position: relative;
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.messages {
  flex: 1;
  min-height: 0;
}
.composer-area {
  flex-shrink: 0;
}
/* Lines up with ChatInput's centered 820px column. */
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 6px 12px;
  max-width: 820px;
  margin: 0 auto;
  padding: 0 24px;
}
.chat-actions {
  display: flex;
  gap: 6px;
}
.chat-actions button {
  padding: 2px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  cursor: pointer;
  font-size: 0.8em;
  color: var(--muted);
  background: transparent;
}
.chat-actions button:hover:not(:disabled) {
  color: var(--text);
  border-color: var(--accent);
}
.chat-actions button:disabled {
  cursor: default;
  opacity: 0.5;
}
.menu {
  display: none;
}
.backdrop {
  display: none;
}

@media (max-width: 767px) {
  .sidebar {
    position: absolute;
    inset: 0 auto 0 0;
    z-index: 20;
    transform: translateX(-100%);
    transition: transform 0.2s ease;
  }
  .sidebar.open {
    transform: none;
  }
  .backdrop {
    display: block;
    position: absolute;
    inset: 0;
    z-index: 10;
    background: rgba(0, 0, 0, 0.35);
  }
  /* Room for the floating menu button above the first message. */
  .messages :deep(.column) {
    padding-top: 52px;
  }
  .menu {
    display: grid;
    place-items: center;
    position: absolute;
    top: 8px;
    left: 8px;
    z-index: 5;
    width: 34px;
    height: 34px;
    border: 1px solid var(--border);
    border-radius: 8px;
    cursor: pointer;
    background: var(--bg);
  }
}
</style>
