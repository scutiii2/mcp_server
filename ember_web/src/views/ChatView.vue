<script setup lang="ts">
import { storeToRefs } from "pinia";
import { ref } from "vue";
import ChatInput from "../components/ChatInput.vue";
import ConversationSidebar from "../components/ConversationSidebar.vue";
import MessageList from "../components/MessageList.vue";
import { useChatStore } from "../stores/chat";

const chat = useChatStore();
// storeToRefs keeps destructured state reactive; actions come off `chat`.
const { sortedConversations, activeId, messages, streaming, activity, busy } = storeToRefs(chat);

// Narrow screens only: the sidebar is a drawer toggled by the menu button.
const drawerOpen = ref(false);

function onNew(): void {
  chat.newChat();
  drawerOpen.value = false;
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
      <ChatInput :busy="busy" @send="chat.send" @stop="chat.stop" />
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
