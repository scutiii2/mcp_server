<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed, onActivated, onDeactivated, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import AgentPicker from "../components/AgentPicker.vue";
import ChatInput from "../components/ChatInput.vue";
import CommandFormModal from "../components/CommandFormModal.vue";
import ConversationSidebar from "../components/ConversationSidebar.vue";
import MessageList from "../components/MessageList.vue";
import ShareDialog from "../components/ShareDialog.vue";
import TemplatesModal from "../components/TemplatesModal.vue";
import { useAgentsStore } from "../stores/agents";
import { useChatStore } from "../stores/chat";
import { useTemplatesStore } from "../stores/templates";
import type { CommandInfo } from "../api/CommandsClient";
import type { JsonSchema } from "../api/types";
import { useChatRoute } from "../composables/useChatRoute";
import { useChatShortcuts } from "../composables/useChatShortcuts";
import { questionHistory } from "../utils/attachments";
import { conversationToMarkdown, downloadText, exportFileName } from "../utils/chatExport";

const chat = useChatStore();
// storeToRefs keeps destructured state reactive; actions come off `chat`.
const {
  sortedConversations,
  activeId,
  active,
  messages,
  streaming,
  activity,
  liveSteps,
  busy,
  caveman,
  listLoading,
  listReady,
  chatLoading,
  loadError,
  saveError,
  sendError,
  working,
  contextUsage,
  commands,
  enabledExtensions,
  askBeforeTools,
  allowedTools,
  pendingApprovals,
  deciding,
  searchQuery,
  searchActive,
  searchHits,
  searching,
  searchError,
} = storeToRefs(chat);
onMounted(() => void chat.loadCommands());
const agentsStore = useAgentsStore();
const templates = useTemplatesStore();

// The saved-prompts dialog; `templatesDraft` is typed text offered as a new prompt.
const templatesOpen = ref(false);
const templatesDraft = ref("");

// The share-link dialog for the open chat.
const shareOpen = ref(false);

function openTemplates(draft: string): void {
  templatesDraft.value = draft;
  templatesOpen.value = true;
}

// The command form: opened when a command with parameters is picked from
// the input's suggestions. Submitting runs the command it builds.
const formCommand = ref<CommandInfo | null>(null);
const formSchema = ref<JsonSchema | null>(null);
const input = ref<InstanceType<typeof ChatInput> | null>(null);

async function openCommandForm(command: CommandInfo): Promise<void> {
  const schema = await chat.commandSchema(command);
  if (!schema) return; // no parameters: the typed command runs as it is
  formSchema.value = schema;
  formCommand.value = command;
}

function closeCommandForm(): void {
  formCommand.value = null;
  formSchema.value = null;
}

function runCommandForm(text: string): void {
  closeCommandForm();
  // An answer is still being written: leave the command ready to send.
  if (busy.value) {
    input.value?.setDraft(text);
    return;
  }
  input.value?.setDraft("");
  void chat.send(text);
}

// Narrow screens only: the sidebar is a drawer toggled by the menu button.
const drawerOpen = ref(false);

// The address bar follows the open chat (/chat/<id>) and the other way round.
// The page is cached behind the other pages (KeepAlive): while it is, the
// address belongs to them.
const shown = ref(false);
const route = useChatRoute(
  {
    activeId,
    listReady,
    hasChat: chat.hasChat,
    selectChat: chat.selectChat,
    newChat: chat.newChat,
    reload: chat.reload,
  },
  shown,
);
const { notFound } = route;
onActivated(() => {
  shown.value = true;
  route.activate();
});
onDeactivated(() => {
  shown.value = false;
});

function onNew(): void {
  route.startNew();
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
  const question = `Start "${conversation.title}" afresh? The agent forgets the earlier messages; they stay readable as a collapsed log.`;
  if (confirm(question)) void chat.clearChat();
}

function summarizeActive(): void {
  const conversation = active.value;
  if (!conversation) return;
  const question = "Condense the earlier messages into a summary? The agent keeps only the summary from now on; the messages stay readable as a collapsed log.";
  if (confirm(question)) void chat.summarizeChat();
}

// Share of the agent's context the last answer used; worth watching past
// about half, since ember_api summarizes automatically at 60%.
const contextPercent = computed(() => {
  const usage = contextUsage.value;
  return usage ? Math.min(100, Math.round((usage.tokens / usage.window) * 100)) : null;
});

function onSelect(id: string, messageIndex?: number): void {
  route.open(id, { messageIndex });
  drawerOpen.value = false;
}

// Tools the user allowed for the open chat ("Allow for this chat").
const allowedCount = computed(() => (activeId.value ? (allowedTools.value[activeId.value]?.length ?? 0) : 0));

// What ↑ and ↓ in the input walk through: what was typed in this chat.
const history = computed(() => questionHistory(messages.value));

useChatShortcuts({
  canStop: () => busy.value,
  stop: () => void chat.stop(),
  focusInput: () => input.value?.focus(),
  newChat: onNew,
});
</script>

<template>
  <section class="chat-view">
    <ConversationSidebar
      :class="['sidebar', { open: drawerOpen }]"
      :conversations="sortedConversations"
      :active-id="activeId"
      :locked="false"
      :loading="listLoading"
      :busy="busy"
      :query="searchQuery"
      :search-active="searchActive"
      :hits="searchHits"
      :searching="searching"
      :search-error="searchError"
      @search="chat.setSearch"
      @new="onNew"
      @select="onSelect"
      @delete="chat.deleteChat"
      @rename="chat.renameChat"
      @delete-all="chat.deleteAllChats"
      @delete-many="chat.deleteChats"
    />
    <div v-if="drawerOpen" class="backdrop" @click="drawerOpen = false" />

    <div class="main">
      <button type="button" class="menu" title="Chats" @click="drawerOpen = true">
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path d="M4 7h16M4 12h16M4 17h16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
        </svg>
      </button>
      <div v-if="saveError || loadError" class="banner" role="alert">
        <template v-if="saveError">
          Couldn't save your chats: {{ saveError }}
          <button type="button" @click="chat.retrySave()">Retry</button>
        </template>
        <template v-else>
          Couldn't load chats: {{ loadError }}
          <button type="button" @click="chat.reload()">Retry</button>
        </template>
      </div>
      <div v-if="notFound" class="banner" role="alert">
        That chat doesn't exist, or it was deleted.
        <button type="button" @click="notFound = false">Dismiss</button>
      </div>
      <div v-if="sendError" class="banner" role="alert">
        {{ sendError }}
        <button type="button" @click="sendError = ''">Dismiss</button>
      </div>
      <p v-if="chatLoading" class="loading">Loading chat …</p>
      <MessageList
        v-else
        class="messages"
        :messages="messages"
        :streaming="streaming"
        :activity="activity"
        :steps="liveSteps"
        :busy="busy"
        :can-change="!busy && !working"
        :approvals="pendingApprovals"
        :deciding="deciding"
        @decide="chat.decideApproval"
        :regenerate-index="chat.regenerateIndex"
        :jump-index="chat.jumpIndex"
        @jumped="chat.clearJump"
        @regenerate="chat.regenerate"
        @branch="chat.branchFrom"
        @edit="chat.editAndResend"
      />
      <div class="composer-area">
        <div class="toolbar">
          <AgentPicker :locked="busy" />
          <label class="terse" title="Ask the agent for short, terse answers">
            <input
              type="checkbox"
              :checked="caveman"
              @change="chat.setCaveman(($event.target as HTMLInputElement).checked)"
            />
            Terse replies
          </label>
          <label class="terse" title="Ask you before the agent runs each tool">
            <input
              type="checkbox"
              :checked="askBeforeTools"
              @change="chat.setAskBeforeTools(($event.target as HTMLInputElement).checked)"
            />
            Ask before tools
          </label>
          <button
            v-if="askBeforeTools && allowedCount"
            type="button"
            class="allowed"
            title="Ask again about the tools you allowed for this chat"
            @click="chat.clearAllowedTools()"
          >
            {{ allowedCount }} tool{{ allowedCount === 1 ? "" : "s" }} allowed - reset
          </button>
          <RouterLink
            to="/extensions"
            class="extensions"
            title="Which extensions' tools the agent may use in your chats"
          >
            Extensions: {{ enabledExtensions.length ? enabledExtensions.join(", ") : "off" }}
          </RouterLink>
          <span
            v-if="contextPercent !== null"
            :class="['context', { high: contextPercent >= 50 }]"
            title="How full the agent's memory of this chat is. At 60% the chat is summarized automatically."
          >
            Context {{ contextPercent }}%
          </span>
          <span v-if="working" class="working">{{ working }}</span>
          <div v-if="active && messages.length" class="chat-actions">
            <button type="button" title="Download this chat as Markdown" @click="exportActive">Export</button>
            <button type="button" title="Make a read-only link to this chat" @click="shareOpen = true">Share</button>
            <button
              type="button"
              title="Condense the earlier messages into a summary the agent keeps"
              :disabled="busy || !!working"
              @click="summarizeActive"
            >
              Summarize
            </button>
            <button type="button" title="Start afresh; earlier messages stay as a log" :disabled="busy || !!working" @click="clearActive">
              Clear
            </button>
          </div>
        </div>
        <ChatInput
          ref="input"
          :busy="busy"
          :commands="commands"
          :history="history"
          :templates="templates.templates"
          :templates-loading="templates.loading"
          :templates-error="templates.loadError"
          @templates-needed="templates.ensureLoaded()"
          @manage-templates="openTemplates"
          @send="chat.send"
          @stop="chat.stop"
          @form="openCommandForm"
        />
        <CommandFormModal :command="formCommand" :schema="formSchema" @submit="runCommandForm" @close="closeCommandForm" />
        <TemplatesModal :open="templatesOpen" :draft="templatesDraft" @close="templatesOpen = false" />
        <ShareDialog :open="shareOpen" :chat-id="activeId" @close="shareOpen = false" />
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
.banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 16px;
  font-size: 0.9em;
  color: var(--danger);
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.banner button {
  padding: 2px 12px;
  border: 1px solid var(--danger);
  border-radius: 999px;
  cursor: pointer;
  color: var(--danger);
  background: transparent;
}
.loading {
  flex: 1;
  margin: 0;
  padding: 24px;
  text-align: center;
  color: var(--muted);
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
.terse {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-right: auto;
  font-size: 0.85em;
  color: var(--muted);
  cursor: pointer;
}
.allowed {
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
  max-width: 220px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-size: 0.8em;
  color: var(--muted);
  text-decoration: none;
}
.extensions:hover {
  color: var(--text);
}
.context,
.working {
  font-size: 0.8em;
  color: var(--muted);
}
.context.high {
  color: var(--danger);
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
