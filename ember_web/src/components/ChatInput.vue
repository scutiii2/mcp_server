<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { attachmentsClient } from "../api/AttachmentsClient";
import type { CommandInfo } from "../api/CommandsClient";
import type { PromptTemplate } from "../api/TemplatesClient";
import { withAttachments } from "../utils/attachments";
import { errorMessage } from "../utils/errors";
import { appendToDraft, filterTemplates, preview, templateQuery } from "../utils/templates";
import TemplatePicker from "./TemplatePicker.vue";

// busy: a turn is running - Send becomes Stop. commands: slash commands to
// suggest while "/..." is being typed (empty without tools.use).
// history: the questions asked in this chat, oldest first. ↑ in an empty box
// brings them back one at a time, ↓ goes forward again.
// templates: the account's saved prompts, for the picker button and for
// "#..." suggestions; the parent loads them when asked (templatesNeeded).
const props = withDefaults(
  defineProps<{
    busy: boolean;
    commands?: CommandInfo[];
    history?: string[];
    templates?: PromptTemplate[];
    templatesLoading?: boolean;
    templatesError?: string;
  }>(),
  { commands: () => [], history: () => [], templates: () => [], templatesLoading: false, templatesError: "" },
);
// form: a command was picked from the suggestions; the chat may open its form.
// templatesNeeded: the picker or a "#" wants the saved prompts.
// manageTemplates: open the templates dialog; `draft` is the typed text to
// save as a new prompt ("" for none).
const emit = defineEmits<{
  send: [question: string];
  stop: [];
  form: [command: CommandInfo];
  templatesNeeded: [];
  manageTemplates: [draft: string];
}>();

const draft = ref("");
// Browsing past questions: which one is shown (null = not browsing). It
// starts only from an empty box, so ↓ past the newest returns to empty.
const recallIndex = ref<number | null>(null);
const textarea = ref<HTMLTextAreaElement | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const dragging = ref(false);

/** A file attached to the next question. Its text is extracted by ember_api
 * as soon as it's added, so sending doesn't wait for an upload. */
interface PendingAttachment {
  id: number;
  filename: string;
  state: "reading" | "ready" | "error";
  text: string;
  chars: number;
  truncated: boolean;
  error: string;
}

let nextAttachmentId = 1;
const attachments = ref<PendingAttachment[]>([]);
const reading = computed(() => attachments.value.some((a) => a.state === "reading"));
const ready = computed(() => attachments.value.filter((a) => a.state === "ready"));
const isCommand = computed(() => draft.value.trimStart().startsWith("/"));
const canSend = computed(
  () => !reading.value && (draft.value.trim() !== "" || (ready.value.length > 0 && !isCommand.value)),
);

async function addFiles(files: FileList | File[] | null | undefined): Promise<void> {
  for (const file of Array.from(files ?? [])) {
    const entry: PendingAttachment = {
      id: nextAttachmentId++,
      filename: file.name,
      state: "reading",
      text: "",
      chars: 0,
      truncated: false,
      error: "",
    };
    attachments.value.push(entry);
    const live = attachments.value[attachments.value.length - 1]!; // the reactive copy
    // Each file on its own: one slow or broken file doesn't hold up the rest.
    void attachmentsClient
      .text(file)
      .then((result) => {
        Object.assign(live, { state: "ready", text: result.text, chars: result.char_count, truncated: result.truncated });
      })
      .catch((err: unknown) => {
        Object.assign(live, { state: "error", error: errorMessage(err) });
      });
  }
}

function removeAttachment(id: number): void {
  attachments.value = attachments.value.filter((a) => a.id !== id);
}

function onPick(event: Event): void {
  const input = event.target as HTMLInputElement;
  void addFiles(input.files);
  input.value = ""; // picking the same file again still fires change
}

function hasFiles(event: DragEvent): boolean {
  return event.dataTransfer?.types.includes("Files") ?? false;
}

// The whole composer is the drop target (suggestions and chips included),
// but dragged text or links are left to the browser.
function onDragOver(event: DragEvent): void {
  if (!hasFiles(event)) return;
  event.preventDefault();
  dragging.value = true;
}

function onDragLeave(event: DragEvent): void {
  // Moving over a child element also fires dragleave on the form.
  if (!(event.currentTarget as HTMLElement).contains(event.relatedTarget as Node | null)) dragging.value = false;
}

function onDrop(event: DragEvent): void {
  dragging.value = false;
  if (!hasFiles(event)) return;
  event.preventDefault();
  void addFiles(event.dataTransfer?.files);
}

/** Pasted files (a screenshot, a file copied in the explorer) become
 * attachments. Pasted text - even with an accompanying image, as copying
 * spreadsheet cells does - pastes as usual. */
function onPaste(event: ClipboardEvent): void {
  const data = event.clipboardData;
  if (!data?.files.length || data.getData("text/plain")) return;
  event.preventDefault();
  void addFiles(data.files);
}

const MAX_SUGGESTIONS = 8;

interface Suggestion {
  text: string;
  description: string;
  /** Set for a runnable command (not help): picking it offers its form. */
  command?: CommandInfo;
  /** Set for a saved prompt: picking it puts its text in the box. */
  template?: PromptTemplate;
}

/** Typing "#..." looks up saved prompts by name. */
const lookingUpTemplate = computed(() => templateQuery(draft.value) !== null);
watch(lookingUpTemplate, (on) => {
  if (on) emit("templatesNeeded");
});

/** Commands matching what's typed, while still on "/<capability> <command>"
 * (suggestions stop once parameters are being typed). */
const suggestions = computed<Suggestion[]>(() => {
  const typed = draft.value;
  const query = templateQuery(typed);
  if (query !== null) {
    return filterTemplates(props.templates, query)
      .slice(0, MAX_SUGGESTIONS)
      .map((t) => ({ text: t.name, description: preview(t.body, 60), template: t }));
  }
  if (!props.commands.length || !/^\/\S*( \S*)?$/.test(typed)) return [];
  const needle = typed.toLowerCase();
  const all: Suggestion[] = [
    { text: "/help", description: "Every capability and its commands" },
    ...[...new Set(props.commands.map((c) => c.capability))].map((cap) => ({
      text: `/${cap} help`,
      description: `How to use ${cap}`,
    })),
    ...props.commands.map((c) => ({ text: `/${c.capability} ${c.name}`, description: c.description, command: c })),
  ];
  return all.filter((s) => s.text.toLowerCase().startsWith(needle) && s.text !== typed).slice(0, MAX_SUGGESTIONS);
});
const highlighted = ref(0);
watch(suggestions, () => (highlighted.value = 0));

function complete(suggestion: Suggestion): void {
  if (suggestion.template) {
    setDraft(suggestion.template.body);
    return;
  }
  draft.value = `${suggestion.text} `;
  void nextTick(() => {
    textarea.value?.focus();
    autoGrow();
  });
  if (suggestion.command) emit("form", suggestion.command);
}

/** The command form was submitted or closed: its text replaces the draft. */
function setDraft(text: string): void {
  draft.value = text;
  void nextTick(() => {
    textarea.value?.focus();
    autoGrow();
  });
}

function focus(): void {
  textarea.value?.focus();
}

/** Adds text to the box: alone in an empty one, else on a new line. */
function insertText(text: string): void {
  setDraft(appendToDraft(draft.value, text));
}

defineExpose({ setDraft, focus, insertText });

/** ↑ and ↓ browse the questions asked before, ready to edit and resend.
 * Starts only from an empty box; once browsing, the arrows still move the
 * caret inside a multi-line question until it reaches the first or last line.
 * True when the key was used. */
function recall(event: KeyboardEvent): boolean {
  const entries = props.history;
  const up = event.key === "ArrowUp";
  const index = recallIndex.value;
  if (index === null) {
    if (!up || draft.value !== "" || entries.length === 0) return false;
    show(entries.length - 1);
  } else {
    const el = event.target as HTMLTextAreaElement;
    const caret = el.selectionStart ?? 0;
    const atEdge = up ? !el.value.slice(0, caret).includes("\n") : !el.value.slice(el.selectionEnd ?? caret).includes("\n");
    if (!atEdge) return false;
    if (up) show(Math.max(0, index - 1));
    else if (index < entries.length - 1) show(index + 1);
    else {
      recallIndex.value = null;
      setDraft("");
    }
  }
  event.preventDefault();
  return true;
}

function show(index: number): void {
  recallIndex.value = index;
  setDraft(props.history[index] ?? "");
}

/** The user typed: whatever is in the box is theirs now, not a recalled question. */
function onInput(): void {
  recallIndex.value = null;
  autoGrow();
}

// A different chat (or a new question) is a different list.
watch(
  () => props.history.join("\u0000"),
  () => (recallIndex.value = null),
);

/** Grow with the content; CSS max-height caps it, then it scrolls. */
function autoGrow(): void {
  const el = textarea.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${el.scrollHeight}px`;
}

function submit(): void {
  if (!canSend.value || props.busy) return;
  const typed = draft.value.trim();
  // Slash commands run a tool, not the agent: attachments wait for a question.
  const files = isCommand.value ? [] : ready.value;
  emit("send", withAttachments(typed, files.map((a) => ({ filename: a.filename, chars: a.chars, truncated: a.truncated, text: a.text }))));
  draft.value = "";
  recallIndex.value = null;
  if (!isCommand.value) attachments.value = attachments.value.filter((a) => a.state !== "ready");
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
  // A saved prompt is not something to send as typed: Enter inserts it.
  if (open && lookingUpTemplate.value && event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    complete(suggestions.value[highlighted.value]!);
    return;
  }
  if (!event.isComposing && (event.key === "ArrowUp" || event.key === "ArrowDown") && recall(event)) return;
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submit();
  }
}
</script>

<template>
  <form class="composer" @submit.prevent="submit" @dragover="onDragOver" @dragleave="onDragLeave" @drop="onDrop">
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
      <li v-if="lookingUpTemplate" class="hint" aria-hidden="true">Tab or Enter inserts the prompt</li>
      <li v-else class="hint" aria-hidden="true">Tab picks (a command opens its form) · Enter runs</li>
    </ul>
    <ul v-if="attachments.length" class="attachments">
      <li v-for="a in attachments" :key="a.id" :class="a.state" :title="a.error || a.filename">
        <span class="name">
          {{ a.state === "reading" ? `Reading ${a.filename} …` : a.state === "error" ? `${a.filename}: ${a.error}` : a.filename }}
          <small v-if="a.state === 'ready' && a.truncated">(cut to {{ a.chars.toLocaleString() }} characters)</small>
        </span>
        <button type="button" :aria-label="`Remove ${a.filename}`" @click="removeAttachment(a.id)">×</button>
      </li>
    </ul>
    <p v-if="recallIndex !== null" class="recall" aria-live="polite">
      Earlier question {{ recallIndex + 1 }} of {{ history.length }} · ↑ older · ↓ newer
    </p>
    <div :class="['box', { dragging }]">
      <input ref="fileInput" type="file" multiple hidden @change="onPick" />
      <button type="button" class="attach" title="Attach files (text, code, PDF, Word, Excel)" @click="fileInput?.click()">
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path
            d="M21 11.5l-8.6 8.6a5 5 0 0 1-7.1-7.1l8.6-8.6a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.6a1.7 1.7 0 0 1-2.4-2.4l7.9-7.9"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </button>
      <TemplatePicker
        :templates="templates"
        :loading="templatesLoading"
        :error="templatesError"
        :can-save="draft.trim() !== ''"
        @open="emit('templatesNeeded')"
        @pick="(template) => insertText(template.body)"
        @manage="emit('manageTemplates', '')"
        @save="emit('manageTemplates', draft.trim())"
      />
      <textarea
        ref="textarea"
        v-model="draft"
        rows="1"
        :placeholder="commands.length ? 'Ask something, / for commands, # for saved prompts' : 'Ask something, # for saved prompts'"
        @input="onInput"
        @keydown="onKeydown"
        @paste="onPaste"
      />
      <button v-if="busy" type="button" class="round stop" title="Stop (Esc)" @click="emit('stop')">
        <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
          <rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor" />
        </svg>
      </button>
      <button v-else type="submit" class="round send" :title="reading ? 'Reading attachments …' : 'Send'" :disabled="!canSend">
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
.box:focus-within,
.box.dragging {
  border-color: var(--accent);
}
.attach {
  display: grid;
  place-items: center;
  width: 30px;
  height: 34px;
  flex-shrink: 0;
  margin-left: -8px;
  padding: 0;
  border: none;
  cursor: pointer;
  color: var(--muted);
  background: transparent;
}
.attach:hover {
  color: var(--text);
}
.recall {
  margin: 0 0 4px 12px;
  font-size: 0.75em;
  color: var(--muted);
}
.attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0 0 6px;
  padding: 0;
  list-style: none;
}
.attachments li {
  display: flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  padding: 2px 4px 2px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 0.8em;
  background: var(--surface);
}
.attachments li.reading {
  color: var(--muted);
}
.attachments li.error {
  border-color: var(--danger);
  color: var(--danger);
}
.attachments .name {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.attachments small {
  color: var(--muted);
}
.attachments button {
  padding: 0 6px;
  border: none;
  cursor: pointer;
  font-size: 1.1em;
  color: inherit;
  background: transparent;
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
