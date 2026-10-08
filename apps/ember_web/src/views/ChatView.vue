<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed, onActivated, onDeactivated, onMounted, ref, watch } from "vue";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import ChatHeader from "../components/ChatHeader.vue";
import ChatInput from "../components/ChatInput.vue";
import ChatSettingsMenu from "../components/ChatSettingsMenu.vue";
import CommandFormModal from "../components/CommandFormModal.vue";
import ElapsedTime from "../components/ElapsedTime.vue";
import ConversationSidebar from "../components/ConversationSidebar.vue";
import FolderDialogs from "../components/FolderDialogs.vue";
import MessageList from "../components/MessageList.vue";
import ShareDialog from "../components/ShareDialog.vue";
import TemplatesModal from "../components/TemplatesModal.vue";
import TurnNotices from "../components/TurnNotices.vue";
import { useEntryAgentStore } from "../stores/entryAgent";
import { useChatStore } from "../stores/chat";
import { useFoldersStore } from "../stores/folders";
import { useTemplatesStore } from "../stores/templates";
import type { CommandInfo } from "../api/CommandsClient";
import type { ChatFolder } from "../api/FoldersClient";
import type { JsonSchema } from "../api/types";
import { useChatRoute } from "../composables/useChatRoute";
import { useChatShortcuts } from "../composables/useChatShortcuts";
import { useFolderCollapse } from "../composables/useFolderCollapse";
import { useSidebarCollapse } from "../composables/useSidebarCollapse";
import { agentLabelFor } from "../utils/agentLabels";
import { builtinCommand, type BuiltinCommand } from "../utils/builtinCommands";
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
  notices,
  working,
  contextUsage,
  commands,
  enabledExtensions,
  askBeforeTools,
  forceToolApproval,
  chime,
  suggestion,
  clockStart,
  allowedTools,
  pendingApprovals,
  deciding,
  pendingQuestions,
  answeringQuestions,
  searchQuery,
  searchActive,
  searchHits,
  searching,
  searchError,
} = storeToRefs(chat);
onMounted(() => void chat.loadCommands());

// Chat folders: the list, which of them are folded, and the new / rename /
// delete dialogs the sidebar's menus open.
const folderStore = useFoldersStore();
const folderCollapse = useFolderCollapse();
const folderDialogs = ref<InstanceType<typeof FolderDialogs> | null>(null);
onMounted(() => void folderStore.ensureLoaded());

/** Every chat filed in the folder, pinned ones included: deleting it deletes them all. */
function chatsIn(folder: ChatFolder): number {
  return sortedConversations.value.filter((c) => c.folderId === folder.id).length;
}

/** "Move to > New folder...": make the folder, then put the chat in it. */
function moveToNewFolder(chatId: string): void {
  folderDialogs.value?.openCreate((folder) => chat.setChatFolder(chatId, folder.id));
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

// The question Save buttons compare against. Loaded once the chat holds a
// question of yours, so a chat without one never asks for the list.
const savedPrompts = computed(() => templates.templates.map((t) => t.body.trim()));
watch(
  () => messages.value.some((m) => m.role === "user"),
  (hasQuestion) => {
    if (hasQuestion) void templates.ensureLoaded();
  },
  { immediate: true },
);

/** Save on a question: a new prompt holding it, or the saved-prompts list when it already is one. */
function saveAsPrompt(text: string): void {
  openTemplates(savedPrompts.value.includes(text.trim()) ? "" : text);
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
  const builtin = builtinCommand(question);
  if (builtin) {
    if (!runBuiltin(builtin)) input.value?.restore(question);
    return;
  }
  if (!(await chat.send(question))) input.value?.restore(question);
}

/** /clear, /compact, /export and /share: the same as the buttons in the chat
 * header, with the same confirms and the same rules. False when refused (an
 * error says why), so the typed text is given back. */
function runBuiltin(command: BuiltinCommand): boolean {
  if (!active.value || messages.value.length === 0) {
    sendError.value = `/${command}: this chat has no messages yet.`;
    return false;
  }
  if ((command === "clear" || command === "compact") && (busy.value || working.value)) {
    sendError.value = `/${command}: wait for the current answer to finish.`;
    return false;
  }
  sendError.value = "";
  if (command === "clear") clearActive();
  else if (command === "compact") summarizeActive();
  else if (command === "export") exportActive();
  else shareOpen.value = true;
  return true;
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

// Clear and compact ask first, in the confirmation dialog.
const pendingChatAction = ref<"clear" | "compact" | null>(null);

const chatActionCopy = computed(() => {
  if (pendingChatAction.value === "clear") {
    return {
      title: "Start afresh",
      message: `Start "${active.value?.title ?? ""}" afresh? The agent forgets the earlier messages; they stay readable as a collapsed log.`,
      label: "Start afresh",
    };
  }
  return {
    title: "Condense messages",
    message:
      "Condense the earlier messages into a summary? The agent keeps only the summary from now on; the messages stay readable as a collapsed log.",
    label: "Condense",
  };
});

function clearActive(): void {
  if (active.value) pendingChatAction.value = "clear";
}

function summarizeActive(): void {
  if (active.value) pendingChatAction.value = "compact";
}

function runChatAction(): void {
  const action = pendingChatAction.value;
  pendingChatAction.value = null;
  if (action === "clear") void chat.clearChat();
  else if (action === "compact") void chat.summarizeChat();
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
      :folders="folderStore.folders"
      :folder-error="folderStore.loadError"
      :collapsed-folders="folderCollapse.collapsed.value"
      @pin="chat.setChatPinned"
      @move="chat.setChatFolder"
      @move-new="moveToNewFolder"
      @toggle-folder="folderCollapse.toggle"
      @new-folder="folderDialogs?.openCreate()"
      @retry-folders="folderStore.ensureLoaded()"
      @rename-folder="(f: ChatFolder) => folderDialogs?.openRename(f)"
      @delete-folder="(f: ChatFolder) => folderDialogs?.openDelete(f, chatsIn(f))"
    />
    <FolderDialogs ref="folderDialogs" />
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
      <ChatHeader
        :title="active?.title ?? 'New chat'"
        :has-messages="!!active && messages.length > 0"
        :context-percent="contextPercent"
        :locked="busy || !!working"
        @export="exportActive"
        @share="shareOpen = true"
        @summarize="summarizeActive"
        @clear="clearActive"
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
      <TurnNotices :notices="notices" @dismiss="chat.dismissNotices()" />
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
        :questions="pendingQuestions"
        :answering-questions="answeringQuestions"
        :approval-required="forceToolApproval"
        :saved-prompts="savedPrompts"
        @save-prompt="saveAsPrompt"
        @decide="chat.decideApproval"
        @answer-question="chat.answerQuestion"
        @skip-question="chat.skipQuestion"
        :regenerate-index="chat.regenerateIndex"
        :jump-index="chat.jumpIndex"
        @jumped="chat.clearJump"
        @regenerate="chat.regenerate"
        @branch="chat.branchFrom"
        @edit="chat.editAndResend"
      />
      <div class="composer-area">
        <ChatInput
          ref="input"
          :busy="busy"
          :commands="commands"
          :history="history"
          :suggestion="suggestion"
          :schema-for="chat.commandSchema"
          :templates="templates.templates"
          :templates-loading="templates.loading"
          :templates-error="templates.loadError"
          @templates-needed="templates.ensureLoaded()"
          @manage-templates="openTemplates"
          @send="onSend"
          @stop="chat.stop"
          @form="openCommandForm"
          @suggestion-used="chat.clearSuggestion"
        >
          <template #tools>
            <ChatSettingsMenu
              :caveman="caveman"
              :ask-before-tools="askBeforeTools"
              :force-tool-approval="forceToolApproval"
              :chime="chime"
              :allowed-count="allowedCount"
              :enabled-extensions="enabledExtensions"
              :attention="pendingApprovals.length > 0"
              @update:caveman="chat.setCaveman"
              @update:ask-before-tools="chat.setAskBeforeTools"
              @update:chime="chat.setChime"
              @clear-allowed="chat.clearAllowedTools()"
            />
            <span v-if="askBeforeTools || forceToolApproval" class="status-chip" title="The agent asks before each tool it runs">
              Ask before tools: on
            </span>
            <span v-if="working" class="working">
              {{ working }}<template v-if="clockStart"> · <ElapsedTime :since="clockStart" /></template>
            </span>
          </template>
        </ChatInput>
        <CommandFormModal :command="formCommand" :schema="formSchema" @submit="runCommandForm" @close="closeCommandForm" />
        <TemplatesModal :open="templatesOpen" :draft="templatesDraft" @close="templatesOpen = false" />
        <ShareDialog :open="shareOpen" :chat-id="activeId" @close="shareOpen = false" />
        <ConfirmModal
          v-if="pendingChatAction"
          open
          :title="chatActionCopy.title"
          :message="chatActionCopy.message"
          :confirm-label="chatActionCopy.label"
          @confirm="runChatAction"
          @close="pendingChatAction = null"
        />
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
  border-radius: var(--radius-full);
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
.status-chip {
  padding: 1px 8px;
  border-radius: var(--radius-full);
  font-size: 0.75em;
  color: var(--muted);
  background: var(--code-bg);
}
.working {
  font-size: 0.8em;
  color: var(--muted);
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
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
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
    border-radius: var(--radius-md);
    cursor: pointer;
    background: var(--bg);
  }
}
</style>
