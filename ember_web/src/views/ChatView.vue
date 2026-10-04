<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed, onActivated, onDeactivated, onMounted, ref } from "vue";
import EntryAgentTag from "../components/EntryAgentTag.vue";
import ChatInput from "../components/ChatInput.vue";
import ChatSettingsMenu from "../components/ChatSettingsMenu.vue";
import CommandFormModal from "../components/CommandFormModal.vue";
import ElapsedTime from "../components/ElapsedTime.vue";
import ConversationSidebar from "../components/ConversationSidebar.vue";
import MessageList from "../components/MessageList.vue";
import ShareDialog from "../components/ShareDialog.vue";
import TemplatesModal from "../components/TemplatesModal.vue";
import { useEntryAgentStore } from "../stores/entryAgent";
import { useChatStore } from "../stores/chat";
import { useTemplatesStore } from "../stores/templates";
import type { CommandInfo } from "../api/CommandsClient";
import type { JsonSchema } from "../api/types";
import { useChatRoute } from "../composables/useChatRoute";
import { useChatShortcuts } from "../composables/useChatShortcuts";
import { useSidebarCollapse } from "../composables/useSidebarCollapse";
import { notificationsSupported } from "../composables/useNotify";
import { agentLabelFor } from "../utils/agentLabels";
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
  forceToolApproval,
  chime,
  notify,
  notifyError,
  clockStart,
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
const notifySupported = notificationsSupported();

/** The checkbox flips by itself; when the browser refuses, put it back to what the store says. */
async function onNotifyChange(event: Event): Promise<void> {
  const box = event.target as HTMLInputElement;
  await chat.setNotify(box.checked);
  box.checked = chat.notify;
}
const entryAgent = useEntryAgentStore();
const agentLabels = computed(() => entryAgent.labels);
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

/** A question ember_api did not take (no entry agent, limit reached ...) goes
 * back into the box, as typed, along with its files. */
async function onSend(question: string): Promise<void> {
  if (!(await chat.send(question))) input.value?.restore(question);
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
// Wider screens: the list can be folded away to give the chat the room.
const { collapsed: sidebarCollapsed, toggle: toggleSidebar } = useSidebarCollapse();

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
  const agentLabel = agentLabelFor(conversation.agentId, entryAgent.labels) ?? null;
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
      :class="['sidebar', { open: drawerOpen, collapsed: sidebarCollapsed }]"
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
    <button
      type="button"
      :class="['collapse', { collapsed: sidebarCollapsed }]"
      :title="sidebarCollapsed ? 'Show chat list' : 'Hide chat list'"
      :aria-label="sidebarCollapsed ? 'Show chat list' : 'Hide chat list'"
      :aria-expanded="!sidebarCollapsed"
      @click="toggleSidebar"
    >
      <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
        <path :d="sidebarCollapsed ? 'M9 5l7 7-7 7' : 'M15 5l-7 7 7 7'" />
      </svg>
    </button>

    <div class="main">
      <button type="button" class="menu" title="Chats" @click="drawerOpen = true">
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path d="M4 7h16M4 12h16M4 17h16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
        </svg>
      </button>
      <ChatSettingsMenu
        :caveman="caveman"
        :ask-before-tools="askBeforeTools"
        :force-tool-approval="forceToolApproval"
        :chime="chime"
        :notify="notify"
        :notify-supported="notifySupported"
        :notify-error="notifyError"
        :allowed-count="allowedCount"
        :enabled-extensions="enabledExtensions"
        :attention="pendingApprovals.length > 0"
        @update:caveman="chat.setCaveman"
        @update:ask-before-tools="chat.setAskBeforeTools"
        @update:chime="chat.setChime"
        @notify="onNotifyChange"
        @clear-allowed="chat.clearAllowedTools()"
      />
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
        :since="clockStart"
        :commands="commands"
        :agent-labels="agentLabels"
        :deciding="deciding"
        :approval-required="forceToolApproval"
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
          <EntryAgentTag />
          <span
            v-if="contextPercent !== null"
            :class="['context', { high: contextPercent >= 50 }]"
            title="How full the agent's memory of this chat is. At 60% the chat is summarized automatically."
          >
            Context {{ contextPercent }}%
          </span>
          <span v-if="working" class="working">
            {{ working }}<template v-if="clockStart"> · <ElapsedTime :since="clockStart" /></template>
          </span>
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
          @send="onSend"
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
/* Status and chat actions sit to the right of the agent tag. */
.toolbar > :first-child {
  margin-right: auto;
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

/* Wider screens: a handle on the list's edge folds it away and back. */
.collapse {
  position: absolute;
  top: 50%;
  left: 260px;
  z-index: 5;
  display: grid;
  place-items: center;
  width: 16px;
  height: 44px;
  padding: 0;
  border: 1px solid var(--border);
  border-left: none;
  border-radius: 0 8px 8px 0;
  cursor: pointer;
  color: var(--muted);
  background: var(--surface);
  transform: translateY(-50%);
  transition: left 0.2s ease;
}
.collapse:hover {
  color: var(--text);
  border-color: var(--accent);
}
.collapse.collapsed {
  left: 0;
}
.collapse svg {
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
@media (min-width: 768px) {
  .sidebar {
    transition:
      width 0.2s ease,
      padding 0.2s ease,
      visibility 0s;
  }
  /* Out of sight and out of the tab order once it has folded. */
  .sidebar.collapsed {
    width: 0;
    padding-inline: 0;
    overflow: hidden;
    border-right-width: 0;
    visibility: hidden;
    transition:
      width 0.2s ease,
      padding 0.2s ease,
      visibility 0s 0.2s;
  }
}

@media (max-width: 767px) {
  .collapse {
    display: none;
  }
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
