<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import type {
  ApprovalDecision,
  ChatMessage,
  PendingApproval,
  PendingQuestion,
  QuestionAnswer,
  ToolStep,
  TurnPlan,
} from "../api/types";
import type { CommandInfo } from "../api/CommandsClient";
import { agentLabelFor } from "../utils/agentLabels";
import { FILE_ONLY_QUESTION, splitAttachments } from "../utils/attachments";
import { hideDownloadMarkers, parseDownloads } from "../utils/downloads";
import { clockTime, dayDividers, fullTime } from "../utils/messageTime";
import { toolTitle } from "../utils/toolTitles";
import ConfirmModal from "./ConfirmModal.vue";
import AgentActivity from "./AgentActivity.vue";
import CopyButton from "./CopyButton.vue";
import DownloadCards from "./DownloadCards.vue";
import ElapsedTime from "./ElapsedTime.vue";
import MarkdownContent from "./MarkdownContent.vue";
import QuestionCard from "./QuestionCard.vue";
import PlanPanel from "./PlanPanel.vue";
import SaveButton from "./SaveButton.vue";
import ToolSteps from "./ToolSteps.vue";
import UsageChip from "./UsageChip.vue";
import WelcomeCard from "./WelcomeCard.vue";

const props = defineProps<{
  messages: ChatMessage[];
  streaming: string;
  activity: string;
  /** The tools the answer being written ran so far. */
  steps: ToolStep[];
  plans?: TurnPlan[];
  busy: boolean;
  /** Messages may be edited or the last answer redone (nothing is running). */
  canChange?: boolean;
  /** Index of the question whose answer Regenerate redoes; -1 for none. */
  regenerateIndex?: number;
  /** A message to scroll to and flash (a search result); null for none. */
  jumpIndex?: number | null;
  /** Tool runs waiting for the user's answer, and the ones already answered
   * but not yet confirmed (their buttons are off). */
  approvals?: PendingApproval[];
  /** The administrator requires approval for every tool: "Allow for this chat" is not offered. */
  approvalRequired?: boolean;
  deciding?: string[];
  /** Questions the agent asked that wait for the user's answer, and the ones
   * already answered but not yet confirmed (their buttons are off). */
  questions?: PendingQuestion[];
  answeringQuestions?: string[];
  /** When the answer being written started (a Date.now() value): shows a running clock. */
  since?: number | null;
  /** The slash commands the account may run, for the welcome card of an empty chat. */
  commands?: CommandInfo[];
  /** Agent ids with the names to show for them, for the tag under each answer. */
  agentLabels?: Record<string, string>;
  /** The texts of the account's saved prompts: a question that matches one
   * shows "Saved". Leave it out to hide the Save button. */
  savedPrompts?: string[];
}>();
const emit = defineEmits<{
  "save-prompt": [text: string];
  regenerate: [];
  edit: [index: number, text: string];
  branch: [index: number];
  jumped: [];
  decide: [stepId: string, decision: ApprovalDecision];
  "answer-question": [stepId: string, answers: QuestionAnswer[]];
  "skip-question": [stepId: string];
}>();

const ARGS_OPEN_MAX_CHARS = 400;

function formatArguments(args: Record<string, unknown>): string {
  return Object.keys(args).length === 0 ? "(no arguments)" : JSON.stringify(args, null, 2);
}

function agentLabel(m: ChatMessage): string | undefined {
  // Without a label the chip shows the saved id.
  return agentLabelFor(m.agent, props.agentLabels ?? {});
}

function isSavedPrompt(text: string): boolean {
  return props.savedPrompts?.includes(text.trim()) ?? false;
}

/** Typed text worth saving as a prompt: not empty, and not the stand-in text of a question that is only files. */
function savableText(index: number): string {
  const part = userParts.value[index];
  if (!part) return "";
  const text = part.text.trim();
  return part.attachments.length > 0 && text === FILE_ONLY_QUESTION ? "" : text;
}

function isDeciding(id: string): boolean {
  return props.deciding?.includes(id) ?? false;
}

// The question being edited (its index) and its draft text.
const editingIndex = ref<number | null>(null);
const editDraft = ref("");
const editArea = ref<HTMLTextAreaElement[]>([]);

async function startEdit(index: number): Promise<void> {
  editingIndex.value = index;
  editDraft.value = userParts.value[index]?.text ?? "";
  await nextTick();
  const area = editArea.value[0];
  if (area) {
    autoGrow(area);
    area.focus();
    area.setSelectionRange(area.value.length, area.value.length);
  }
}

function autoGrow(area: HTMLTextAreaElement): void {
  area.style.height = "auto";
  area.style.height = `${area.scrollHeight}px`;
}

function cancelEdit(): void {
  editingIndex.value = null;
}

// Editing a question that has later exchanges asks before dropping them; the
// edit stays open behind the dialog until it is answered.
const confirmingEdit = ref(false);

function saveEdit(): void {
  const index = editingIndex.value;
  if (index === null) return;
  const hasFiles = (userParts.value[index]?.attachments.length ?? 0) > 0;
  if (!editDraft.value.trim() && !hasFiles) return;
  // Everything after this question goes: ask before dropping later exchanges.
  const later = props.messages.slice(index + 1).some((m) => m.role === "user" && !m.kind);
  if (later) {
    confirmingEdit.value = true;
    return;
  }
  sendEdit(index);
}

function confirmEdit(): void {
  confirmingEdit.value = false;
  if (editingIndex.value !== null) sendEdit(editingIndex.value);
}

function sendEdit(index: number): void {
  editingIndex.value = null;
  emit("edit", index, editDraft.value);
}

// A running answer or a switched chat closes an open edit.
watch(
  () => [props.busy, props.canChange === false],
  () => (editingIndex.value = null),
);

// The day label above the first message of each day (null: none). `now` is
// read when the list changes, so "Today" can be stale after midnight until then.
const dividers = computed(() => dayDividers(props.messages));

// A question's attached files, shown collapsed under what was typed.
const userParts = computed(() =>
  props.messages.map((m) => (m.role === "user" && !m.kind ? splitAttachments(m.content) : null)),
);

// Within this many px of the bottom counts as "following along".
const STICK_THRESHOLD_PX = 80;

const scroller = ref<HTMLElement | null>(null);
// Follow new content only while the user is at the bottom; scrolling up to
// read something stops it, scrolling back down resumes it.
const stickToBottom = ref(true);
// Something arrived while the user was reading further up: shows the
// "New messages" pill, which brings them back down.
const hasNew = ref(false);

function onScroll(): void {
  const el = scroller.value;
  if (!el) return;
  stickToBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD_PX;
  if (stickToBottom.value) hasNew.value = false;
}

function jumpToNew(): void {
  const el = scroller.value;
  if (!el) return;
  stickToBottom.value = true;
  hasNew.value = false;
  el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
}

async function scrollToBottomIfSticking(): Promise<void> {
  if (!stickToBottom.value) return;
  await nextTick();
  const el = scroller.value;
  if (el) el.scrollTop = el.scrollHeight;
}

watch(
  () => props.messages.length,
  (count, before) => {
    // Sending a question always jumps back to the bottom.
    if (props.messages.at(-1)?.role === "user") stickToBottom.value = true;
    if (!stickToBottom.value && count > before) hasNew.value = true;
    void scrollToBottomIfSticking();
  },
);
watch(
  () => [props.streaming, props.activity, props.steps.length],
  () => {
    if (!stickToBottom.value) hasNew.value = true;
    void scrollToBottomIfSticking();
  },
);

const FLASH_MS = 1600;
// The message a search result pointed at, highlighted for a moment.
const flashIndex = ref<number | null>(null);
let flashTimer: ReturnType<typeof setTimeout> | null = null;

// Scrolls to the requested message once it is rendered (immediate: this list
// only mounts after the chat's transcript has loaded). A target past the end
// of the chat is dropped.
watch(
  () => [props.jumpIndex, props.messages.length] as const,
  async ([index, count]) => {
    if (index === null || index === undefined) return;
    if (index >= count) {
      emit("jumped");
      return;
    }
    await nextTick();
    const target = scroller.value?.querySelector<HTMLElement>(`[data-index="${index}"]`);
    if (!target) return;
    stickToBottom.value = false; // reading history: don't follow new content
    target.scrollIntoView({ block: "center" });
    flashIndex.value = index;
    if (flashTimer !== null) clearTimeout(flashTimer);
    flashTimer = setTimeout(() => (flashIndex.value = null), FLASH_MS);
    emit("jumped");
  },
  { immediate: true, flush: "post" },
);

onBeforeUnmount(() => {
  if (flashTimer !== null) clearTimeout(flashTimer);
});
</script>

<template>
  <div class="list">
  <div ref="scroller" class="scroller" @scroll.passive="onScroll">
    <div class="column">
      <WelcomeCard v-if="messages.length === 0 && !busy" :commands="commands ?? []" />

      <template v-for="(m, i) in messages" :key="i">
      <div v-if="dividers[i]" class="day-divider" role="separator"><span>{{ dividers[i] }}</span></div>
      <div :class="['msg', { flash: flashIndex === i }]" :data-index="i">
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
        <div v-else-if="m.kind === 'command'" class="assistant command-reply">
          <MarkdownContent class="command-result" :text="parseDownloads(m.content).text" />
          <DownloadCards :downloads="parseDownloads(m.content).downloads" />
          <div class="actions">
            <time v-if="m.at" class="stamp" :datetime="m.at" :title="fullTime(m.at)">{{ clockTime(m.at) }}</time>
            <UsageChip :message="m" :agent-label="agentLabel(m)" />
          </div>
        </div>
        <!-- Only model output is rendered as markdown; the user's own text stays literal. -->
        <div v-else-if="m.role === 'user' && editingIndex === i" class="user-row editing">
          <textarea
            ref="editArea"
            v-model="editDraft"
            class="edit-area"
            rows="2"
            aria-label="Edit your question"
            @input="autoGrow($event.target as HTMLTextAreaElement)"
            @keydown.esc.prevent="cancelEdit"
            @keydown.enter.exact.prevent="saveEdit"
          />
          <p v-if="userParts[i]?.attachments.length" class="edit-note">
            Attached files stay with the question ({{ userParts[i]?.attachments.length }}).
          </p>
          <div class="actions">
            <button type="button" class="ghost" @click="cancelEdit">Cancel</button>
            <button type="button" class="primary" @click="saveEdit">Save &amp; resend</button>
          </div>
        </div>
        <div v-else-if="m.role === 'user'" class="user-row">
          <div class="user-bubble">
            <template v-if="userParts[i]?.text">{{ userParts[i]?.text }}</template>
            <details v-for="(a, j) in userParts[i]?.attachments ?? []" :key="j" class="attachment">
              <summary>📎 {{ a.filename }} ({{ a.chars.toLocaleString() }} characters{{ a.truncated ? ", cut short" : "" }})</summary>
              <pre>{{ a.text }}</pre>
            </details>
          </div>
          <div class="actions user-actions">
            <time v-if="m.at" class="stamp" :datetime="m.at" :title="fullTime(m.at)">{{ clockTime(m.at) }}</time>
            <CopyButton :text="userParts[i]?.text || m.content" label="Copy message" />
            <SaveButton
              v-if="savedPrompts && savableText(i)"
              small
              :saved="isSavedPrompt(savableText(i))"
              :title="isSavedPrompt(savableText(i)) ? 'Already one of your saved prompts' : 'Save as a prompt'"
              @click="emit('save-prompt', savableText(i))"
            />
            <button v-if="canChange" type="button" class="action" title="Edit and resend" aria-label="Edit and resend" @click="startEdit(i)">
              <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                <path
                  d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4zM13.5 6.5l4 4"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
          </div>
        </div>
        <div v-else class="assistant">
          <ToolSteps v-if="m.steps?.length" :steps="m.steps" class="saved-steps" />
          <MarkdownContent :text="parseDownloads(m.content).text" />
          <DownloadCards :downloads="parseDownloads(m.content).downloads" />
          <div class="actions">
            <time v-if="m.at" class="stamp" :datetime="m.at" :title="fullTime(m.at)">{{ clockTime(m.at) }}</time>
            <CopyButton :text="parseDownloads(m.content).text" label="Copy answer" />
            <button
              v-if="canChange && i === messages.length - 1 && regenerateIndex !== undefined && regenerateIndex >= 0"
              type="button"
              class="action"
              title="Regenerate answer"
              aria-label="Regenerate answer"
              @click="emit('regenerate')"
            >
              <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                <path
                  d="M20 12a8 8 0 1 1-2.6-5.9M20 4v5h-5"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
            <button
              v-if="canChange"
              type="button"
              class="action"
              title="Branch: continue from here in a new chat"
              aria-label="Branch from this answer"
              @click="emit('branch', i)"
            >
              <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                <circle cx="7" cy="6" r="2" fill="none" stroke="currentColor" stroke-width="1.8" />
                <circle cx="7" cy="18" r="2" fill="none" stroke="currentColor" stroke-width="1.8" />
                <circle cx="17" cy="8" r="2" fill="none" stroke="currentColor" stroke-width="1.8" />
                <path
                  d="M7 8v8M17 10c0 4-10 2-10 6"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                  stroke-linecap="round"
                />
              </svg>
            </button>
            <UsageChip :message="m" :agent-label="agentLabel(m)" />
          </div>
        </div>
      </div>
      </template>

      <div v-if="busy" class="assistant live">
        <PlanPanel :plans="plans ?? []" />
        <ToolSteps v-if="steps.length" :steps="steps" live />
        <!-- A tool the agent wants to run waits here; nothing runs until the
             user answers (or a few minutes pass, which counts as no). What is
             shown is the tool's real name and arguments, not the model's words. -->
        <section
          v-for="a in approvals ?? []"
          :key="a.id"
          class="approval"
          role="group"
          :aria-label="`Allow ${toolTitle(a.tool)}?`"
        >
          <header>
            <strong>{{ a.label || toolTitle(a.tool) }}</strong>
            <code>{{ a.tool }}</code>
          </header>
          <p class="ask">The agent wants to run this tool. It will not run until you allow it.</p>
          <details :open="formatArguments(a.arguments).length <= ARGS_OPEN_MAX_CHARS">
            <summary>Arguments</summary>
            <pre>{{ formatArguments(a.arguments) }}</pre>
          </details>
          <div class="buttons">
            <button type="button" class="allow" :disabled="isDeciding(a.id)" @click="emit('decide', a.id, 'allow')">
              Allow once
            </button>
            <button
              v-if="!approvalRequired"
              type="button"
              :disabled="isDeciding(a.id)"
              @click="emit('decide', a.id, 'always')"
            >
              Allow for this chat
            </button>
            <button type="button" class="deny" :disabled="isDeciding(a.id)" @click="emit('decide', a.id, 'deny')">
              Deny
            </button>
          </div>
          <p class="note">No answer within 4 minutes counts as Deny.</p>
        </section>
        <!-- The agent asked the user something and waits for the answer (no
             time limit: they may be deciding). Nothing continues until they
             answer or skip. -->
        <QuestionCard
          v-for="q in questions ?? []"
          :key="q.id"
          :pending="q"
          :answering="answeringQuestions?.includes(q.id) ?? false"
          @answer="(id, answers) => emit('answer-question', id, answers)"
          @skip="(id) => emit('skip-question', id)"
        />
        <AgentActivity />
        <span v-if="activity" class="activity"><span class="dot" />{{ activity }}</span>
        <MarkdownContent v-if="streaming" :text="hideDownloadMarkers(streaming)" />
        <span v-else-if="!activity" class="activity"><span class="dot" />thinking ...</span>
        <ElapsedTime v-if="since" :since="since" class="elapsed" />
      </div>
    </div>
  </div>
  <Transition name="pill">
    <button v-if="hasNew && !stickToBottom" type="button" class="new-pill" @click="jumpToNew">↓ New messages</button>
  </Transition>
  <ConfirmModal
    v-if="confirmingEdit"
    open
    title="Edit question"
    message="Editing this question discards the messages after it. Continue?"
    confirm-label="Discard and resend"
    @confirm="confirmEdit"
    @close="confirmingEdit = false"
  />
  </div>
</template>

<style scoped>
.list {
  position: relative;
  display: flex;
  flex-direction: column;
}
.scroller {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.new-pill {
  position: absolute;
  bottom: 12px;
  left: 50%;
  translate: -50% 0;
  padding: 6px 14px;
  border: none;
  border-radius: var(--radius-full);
  cursor: pointer;
  font: inherit;
  font-size: 0.85em;
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
  box-shadow: 0 2px 10px rgb(0 0 0 / 0.25);
}
.pill-enter-active,
.pill-leave-active {
  transition:
    opacity 0.2s ease,
    transform 0.2s ease;
}
.pill-enter-from,
.pill-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
@media (prefers-reduced-motion: reduce) {
  .pill-enter-active,
  .pill-leave-active {
    transition: none;
  }
}
.column {
  max-width: 820px;
  margin: 0 auto;
  padding: 24px 16px 8px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.elapsed {
  display: block;
  margin-top: 4px;
  font-size: 0.8em;
  color: var(--muted);
}
/* One wrapper per message (the scroll-to target); a column so children keep
   their own alignment (align-self on the command bubble, .user-row). */
.msg {
  display: flex;
  flex-direction: column;
  border-radius: var(--radius-lg);
}
.msg.flash {
  animation: flash 1.6s ease-out;
}
@keyframes flash {
  0%,
  40% {
    background: color-mix(in srgb, var(--accent) 22%, transparent);
  }
}
.user-bubble.command {
  align-self: flex-end;
}
.user-row {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}
.actions {
  display: flex;
  flex-wrap: wrap; /* the usage panel wraps onto its own line */
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}
.user-actions {
  margin-top: 0;
}
.stamp {
  font-size: 0.75em;
  color: var(--muted);
}
/* A line with the day in the middle, between the messages of two days. */
.day-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.75em;
  color: var(--muted);
}
.day-divider::before,
.day-divider::after {
  content: "";
  flex: 1;
  border-top: 1px solid var(--border);
}
.action {
  display: inline-flex;
  align-items: center;
  padding: 2px 6px;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--muted);
  background: transparent;
}
.action:hover {
  color: var(--text);
  background: var(--surface);
}
/* Shown on hover or keyboard focus; always on touch screens. */
.user-actions,
.assistant .actions .stamp,
.assistant .actions :deep(.copy),
.assistant .actions .action {
  opacity: 0;
  transition: opacity 0.1s;
}
.user-row:hover .user-actions,
.assistant:hover .actions .stamp,
.assistant:hover .actions :deep(.copy),
.assistant:hover .actions .action,
.actions:focus-within .stamp,
.actions:focus-within :deep(.copy),
.actions:focus-within .action,
.user-actions:focus-within {
  opacity: 1;
}
@media (hover: none) {
  .user-actions,
  .assistant .actions .stamp,
  .assistant .actions :deep(.copy),
  .assistant .actions .action {
    opacity: 1;
  }
}
.editing {
  width: min(100%, 560px);
  align-self: flex-end;
}
.edit-area {
  width: 100%;
  max-height: calc(1.55em * 10);
  padding: 10px 14px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-lg);
  outline: none;
  resize: none;
  background: var(--surface);
}
.edit-note {
  margin: 0;
  font-size: 0.75em;
  color: var(--muted);
}
.editing .actions {
  margin-top: 0;
}
.ghost,
.primary {
  padding: 4px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  cursor: pointer;
  font-size: 0.85em;
}
.ghost {
  color: var(--muted);
  background: transparent;
}
.primary {
  border-color: var(--accent);
  color: var(--accent-contrast);
  background: var(--accent);
}
.user-bubble {
  max-width: 80%;
  padding: 10px 14px;
  border-radius: var(--radius-xl) var(--radius-xl) var(--radius-sm) var(--radius-xl);
  background: var(--user-bubble);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.assistant {
  overflow-wrap: anywhere;
}
/* An answer sits beside a small round mark; everything in it goes in the second
   column. A command's result (a tool's output, not the agent's words) looks the
   same, with a plain "/" mark instead of the accent-colored spark. */
.assistant {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  column-gap: 10px;
  align-items: start;
}
.assistant::before {
  content: "✦";
  grid-column: 1;
  grid-row: 1;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-full);
  font-size: 0.8em;
  color: var(--accent-contrast);
  background: var(--accent);
}
.assistant.command-reply::before {
  content: "/";
  border: 1px solid var(--border);
  font-family: var(--mono);
  font-weight: 600;
  color: var(--muted);
  background: var(--surface);
}
.assistant > * {
  grid-column: 2;
}
.attachment {
  margin-top: 6px;
  white-space: normal;
  font-size: 0.85em;
}
.attachment summary {
  cursor: pointer;
}
.attachment pre {
  max-height: 240px;
  margin: 6px 0 0;
  padding: 8px;
  overflow: auto;
  border-radius: var(--radius-md);
  white-space: pre-wrap;
  font-family: var(--mono);
  background: var(--bg);
}
.saved-steps {
  margin-bottom: 6px;
}
.command {
  font-family: var(--mono);
  font-size: 0.9em;
}
.summary {
  padding: 10px 14px;
  border-left: 3px solid var(--accent);
  border-radius: var(--radius-sm);
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
  border-radius: var(--radius-md);
  white-space: pre-wrap;
  font-family: var(--mono);
  background: var(--code-bg);
}
.approval {
  padding: 10px 12px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--accent) 6%, var(--surface));
}
.approval header {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
}
.approval code {
  font-family: var(--mono);
  font-size: 0.8em;
  color: var(--muted);
}
.approval .ask {
  margin: 4px 0;
  font-size: 0.9em;
}
.approval details {
  margin: 4px 0 8px;
  font-size: 0.85em;
}
.approval summary {
  cursor: pointer;
  color: var(--muted);
}
.approval pre {
  max-height: 220px;
  margin: 6px 0 0;
  padding: 8px;
  overflow: auto;
  border-radius: calc(var(--radius-lg) - 10px);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: var(--mono);
  background: var(--code-bg);
}
.approval .buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.approval .buttons button {
  padding: 5px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  cursor: pointer;
  font-size: 0.85em;
  color: var(--text);
  background: transparent;
}
.approval .buttons button:hover:not(:disabled) {
  border-color: var(--accent);
}
.approval .buttons .allow {
  border-color: var(--accent);
  color: var(--accent-contrast);
  background: var(--accent);
}
.approval .buttons .deny:hover:not(:disabled) {
  border-color: var(--danger);
  color: var(--danger);
}
.approval .buttons button:disabled {
  cursor: default;
  opacity: 0.45;
}
.approval .note {
  margin: 8px 0 0;
  font-size: 0.75em;
  color: var(--muted);
}
.live {
  row-gap: 8px;
}
/* The status pills and the clock keep their own width. */
.live > .activity,
.live > .elapsed {
  justify-self: start;
}
.activity {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 3px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  font-size: 0.85em;
  color: var(--muted);
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  background: var(--accent);
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
  50% {
    opacity: 0.3;
  }
}
</style>
