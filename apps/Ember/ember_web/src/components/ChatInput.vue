<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, ref, watch } from "vue";
import { useAuthStore } from "../stores/auth";
import { attachmentsClient } from "../api/AttachmentsClient";
import type { CommandInfo } from "../api/CommandsClient";
import type { PromptTemplate } from "../api/TemplatesClient";
import type { JsonSchema } from "../api/types";
import { BUILTIN_COMMANDS } from "../utils/builtinCommands";
import { splitAttachments, PDF_FILE, TABLE_FILE, tableHeader, withAttachments } from "../utils/attachments";
import { paramSuggestions } from "../utils/commandParams";
import { errorMessage } from "../utils/errors";
import { appendToDraft, filterTemplates, preview, templateQuery } from "../utils/templates";
import { fieldsFromSchema, type ToolField } from "../utils/toolSchema";
import TemplatePicker from "./TemplatePicker.vue";
import type ListComposerInstance from "./ListComposer.vue";
import { hasComposerList } from "../utils/composerLists";

let listModule: Promise<typeof import("./ListComposer.vue")> | undefined;
const loadListComposer = () => listModule ??= import("./ListComposer.vue");
const ListComposer = defineAsyncComponent(loadListComposer);

// busy: a turn is running - Send becomes Stop. commands: slash commands to
// suggest while "/..." is being typed (empty without tools.view).
// history: the questions asked in this chat, oldest first. ↑ in an empty box
// brings them back one at a time, ↓ goes forward again.
// templates: the account's saved prompts, for the picker button and for
// "#..." suggestions; the parent loads them when asked (templatesNeeded).
// schemaFor: a command's parameter schema, for "key=value" suggestions.
const props = withDefaults(
  defineProps<{
    busy: boolean;
    commands?: CommandInfo[];
    history?: string[];
    templates?: PromptTemplate[];
    schemaFor?: (command: CommandInfo) => Promise<JsonSchema | null>;
    templatesLoading?: boolean;
    templatesError?: string;
    suggestion?: string | null;
  }>(),
  { commands: () => [], history: () => [], templates: () => [], templatesLoading: false, templatesError: "", suggestion: null },
);
// suggestion: the predicted next question. It is the placeholder while the box
// is empty; Tab on the empty box takes it (suggestionUsed), and it can be edited.
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
  suggestionUsed: [];
}>();

const draft = ref("");
/** Counts sends; non-zero while the paper plane is in the air (also its :key, so each send restarts it). */
const flights = ref(0);
// Browsing past questions: which one is shown (null = not browsing). It
// starts only from an empty box, so ↓ past the newest returns to empty.
const recallIndex = ref<number | null>(null);
const textarea = ref<HTMLTextAreaElement | null>(null);
const listEditor = ref<InstanceType<typeof ListComposerInstance> | null>(null);
const listMode = ref(false);
const initialListCaret = ref<number | undefined>(undefined);
watch(draft, async (value) => {
  if (value === "") {
    const wasEditing = document.activeElement?.closest(".list-composer") != null;
    listMode.value = false;
    if (wasEditing) void nextTick(() => textarea.value?.focus());
  } else if (!listMode.value && hasComposerList(value)) {
    // Keep the native field editable while the optional editor module loads.
    await loadListComposer();
    if (hasComposerList(draft.value)) {
      initialListCaret.value = textarea.value?.selectionStart;
      listMode.value = true;
    }
  }
});
const auth = useAuthStore();
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
  /** Rows and columns of the table mcp_server kept (0 for any other file). */
  rows: number;
  columns: number;
  error: string;
  pages?: number;
}

let nextAttachmentId = 1;
const attachments = ref<PendingAttachment[]>([]);
const reading = computed(() => attachments.value.some((a) => a.state === "reading"));
const ready = computed(() => attachments.value.filter((a) => a.state === "ready"));
const isCommand = computed(() => draft.value.trimStart().startsWith("/"));
const canSend = computed(
  () => !reading.value && (draft.value.trim() !== "" || (ready.value.length > 0 && !isCommand.value)),
);
const placeholder = computed(() => {
  if (draft.value === "" && props.suggestion) return props.suggestion;
  return props.commands.length
    ? "Ask something, / for commands, # for saved prompts"
    : "Ask something, # for saved prompts";
});


async function addFiles(files: FileList | File[] | null | undefined): Promise<void> {
  if (!auth.hasPermission("files.upload")) return;
  for (const file of Array.from(files ?? [])) {
    const entry: PendingAttachment = {
      id: nextAttachmentId++,
      filename: file.name,
      state: "reading",
      text: "",
      chars: 0,
      truncated: false,
      rows: 0,
      columns: 0,
      error: "",
    };
    attachments.value.push(entry);
    const live = attachments.value[attachments.value.length - 1]!; // the reactive copy
    if (PDF_FILE.test(file.name)) {
      void attachmentsClient.pdf(file).then((result) => {
        Object.assign(live, {
          state: "ready",
          text: `[PDFMerger file_id: ${result.file_id} | ${result.pages} pages | ${result.kind} | expires_at: ${result.expires_at} | use pdf_merger tools to inspect/merge this original; preserve this file_id when delegating to PDF Assistant]\n` +
            (result.text || "[No text preview available; the original file is available for inspection and merging.]"),
          chars: result.char_count, truncated: result.truncated, pages: result.pages,
        });
      }).catch((err: unknown) => Object.assign(live, { state: "error", error: errorMessage(err) }));
      continue;
    }
    // A .csv / .xlsx is also uploaded whole, so the data tools can read every
    // row; the text preview stays as the fallback if that upload fails.
    const wantsTable = TABLE_FILE.test(file.name);
    const tableUpload = wantsTable ? attachmentsClient.table(file).catch(() => null) : Promise.resolve(null);
    // Each file on its own: one slow or broken file doesn't hold up the rest.
    void Promise.all([attachmentsClient.text(file), tableUpload])
      .then(([result, uploaded]) => {
        Object.assign(live, {
          state: "ready",
          text: (wantsTable ? tableHeader(uploaded) : "") + result.text,
          chars: result.char_count,
          truncated: result.truncated,
          rows: uploaded?.rows ?? 0,
          columns: uploaded?.columns.length ?? 0,
        });
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
  /** Set for a parameter ("key=" or "key=value"): picking it replaces the
   * word being typed, which starts here, instead of the whole box. */
  replaceFrom?: number;
}

/** The command being filled in ("/<capability> <command> " typed, parameters
 * after it) with its parameters; null until its schema has loaded. */
const typedCommand = computed(() => {
  const match = /^\/(\S+) (\S+) /.exec(draft.value);
  const command = match && props.commands.find((c) => c.capability === match[1] && c.name === match[2]);
  return command ? { command, prefix: match[0].length } : null;
});
const schemas = ref<Record<string, ToolField[]>>({});
watch(
  () => typedCommand.value?.command,
  async (command) => {
    if (!command || !props.schemaFor || command.tool_name in schemas.value) return;
    const schema = await props.schemaFor(command);
    schemas.value[command.tool_name] = schema ? fieldsFromSchema(schema) : [];
  },
  { immediate: true },
);
// Extensions changed: the same command may now have another schema.
watch(
  () => props.commands,
  () => (schemas.value = {}),
);
const paramContext = computed(() => {
  const typed = typedCommand.value;
  const fields = typed && schemas.value[typed.command.tool_name];
  return typed && fields?.length ? { fields, prefix: typed.prefix } : null;
});

/** Typing "#..." looks up saved prompts by name. */
const lookingUpTemplate = computed(() => templateQuery(draft.value) !== null);
watch(lookingUpTemplate, (on) => {
  if (on) emit("templatesNeeded");
});

/** Commands matching what's typed, while still on "/<capability> <command>"
 * (suggestions stop once parameters are being typed). */
const suggestions = computed<Suggestion[]>(() => {
  const typed = draft.value;
  if (paramContext.value) {
    const { fields, prefix } = paramContext.value;
    return paramSuggestions(fields, typed.slice(prefix))
      .slice(0, MAX_SUGGESTIONS)
      .map((p) => ({ text: p.text, description: p.description, replaceFrom: prefix + p.start }));
  }
  const query = templateQuery(typed);
  if (query !== null) {
    return filterTemplates(props.templates, query)
      .slice(0, MAX_SUGGESTIONS)
      .map((t) => ({ text: t.name, description: preview(t.body, 60), template: t }));
  }
  if (!/^\/\S*( \S*)?$/.test(typed)) return [];
  const needle = typed.toLowerCase();
  const all: Suggestion[] = [
    // The built-ins work without any tools, so they are offered even before commands load.
    ...BUILTIN_COMMANDS.map((c) => ({ text: `/${c.name}`, description: c.description })),
    ...(props.commands.length ? [{ text: "/help", description: "Every capability and its commands" }] : []),
    ...[...new Set(props.commands.map((c) => c.capability))].map((cap) => ({
      text: `/${cap} help`,
      description: `How to use ${cap}`,
    })),
    ...props.commands.map((c) => ({ text: `/${c.capability} ${c.name}`, description: c.description, command: c })),
  ];
  return all.filter((s) => s.text.toLowerCase().startsWith(needle) && s.text !== typed).slice(0, MAX_SUGGESTIONS);
});
const highlighted = ref(0);
const list = ref<HTMLUListElement | null>(null);
watch(suggestions, () => (highlighted.value = 0));
// Keep the highlighted row visible when the arrows move it past the list's edge.
// The list is its own scroll box, so move its scrollTop directly instead of
// scrollIntoView, which also scrolls ancestors and is a no-op in some layouts.
watch(highlighted, () => {
  void nextTick(() => {
    const box = list.value;
    const row = box?.querySelector<HTMLElement>("li.active");
    if (!box || !row) return;
    const pad = row.offsetTop - box.scrollTop;
    if (pad < 0) box.scrollTop = row.offsetTop - 4;
    else if (pad + row.offsetHeight > box.clientHeight) box.scrollTop = row.offsetTop + row.offsetHeight - box.clientHeight + 4;
  });
});

function complete(suggestion: Suggestion): void {
  if (suggestion.replaceFrom !== undefined) {
    // "key=" stays open for its value; a finished "key=value" is followed by a space.
    draft.value = `${draft.value.slice(0, suggestion.replaceFrom)}${suggestion.text}${suggestion.text.endsWith("=") ? "" : " "}`;
    void nextTick(() => {
      focus();
      autoGrow();
    });
    return;
  }
  if (suggestion.template) {
    setDraft(suggestion.template.body);
    return;
  }
  draft.value = `${suggestion.text} `;
  void nextTick(() => {
    focus();
    autoGrow();
  });
  if (suggestion.command) emit("form", suggestion.command);
}

/** The command form was submitted or closed: its text replaces the draft. */
function setDraft(text: string): void {
  draft.value = text;
  void nextTick(() => {
    focus();
    autoGrow();
  });
}

function focus(): void {
  if (listMode.value) listEditor.value?.focus();
  else textarea.value?.focus();
}

/** Adds text to the box: alone in an empty one, else on a new line. */
function insertText(text: string): void {
  setDraft(appendToDraft(draft.value, text));
}

/** Gives back a question that was not taken (ember_api refused it), as typed:
 * the text, and its files as ready attachments. Only into an empty box, so
 * whatever the person has typed since is never overwritten. */
function restore(question: string): void {
  if (draft.value.trim() !== "" || attachments.value.length > 0) return;
  const { text, attachments: files } = splitAttachments(question);
  for (const file of files) {
    attachments.value.push({ id: nextAttachmentId++, filename: file.filename, state: "ready", text: file.text, chars: file.chars, truncated: file.truncated, rows: 0, columns: 0, error: "" });
  }
  setDraft(text);
}

defineExpose({ setDraft, focus, insertText, restore });

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
    const atEdge = listMode.value
      ? (listEditor.value?.atHistoryEdge(up) ?? false)
      : up ? !el.value.slice(0, caret).includes("\n") : !el.value.slice(el.selectionEnd ?? caret).includes("\n");
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
  if (listMode.value) return;
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
  flights.value++;
  draft.value = "";
  recallIndex.value = null;
  if (!isCommand.value) attachments.value = attachments.value.filter((a) => a.state !== "ready");
  void nextTick(autoGrow);
}

/** Enter sends, Shift+Enter is a newline. isComposing: never send while an
 * IME (Japanese/Chinese input) is still composing a character. */
function onKeydown(event: KeyboardEvent): void {
  const open = suggestions.value.length > 0;
  // The predicted next question: Tab on an empty box takes it.
  if (
    event.key === "Tab" &&
    !event.shiftKey &&
    !event.isComposing &&
    !open &&
    draft.value === "" &&
    props.suggestion
  ) {
    event.preventDefault();
    draft.value = props.suggestion;
    recallIndex.value = null;
    emit("suggestionUsed");
    void nextTick(() => {
      autoGrow();
      const end = draft.value.length;
      if (listMode.value) listEditor.value?.focusEnd();
      else textarea.value?.setSelectionRange(end, end);
    });
    return;
  }
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
    <div v-if="suggestions.length" class="suggestions">
      <ul ref="list" class="options" role="listbox" aria-label="Commands">
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
      </ul>
      <p v-if="lookingUpTemplate" class="hint" aria-hidden="true">Tab or Enter inserts the prompt</p>
      <p v-else-if="paramContext" class="hint" aria-hidden="true">Tab picks · Enter runs</p>
      <p v-else class="hint" aria-hidden="true">Tab picks (a command opens its form) · Enter runs</p>
    </div>
    <ul v-if="attachments.length" class="attachments">
      <li v-for="a in attachments" :key="a.id" :class="a.state" :title="a.error || a.filename">
        <span class="name">
          {{ a.state === "reading" ? `Reading ${a.filename} …` : a.state === "error" ? `${a.filename}: ${a.error}` : a.filename }}
          <small v-if="a.state === 'ready' && a.truncated">(cut to {{ a.chars.toLocaleString() }} characters)</small>
          <small v-if="a.state === 'ready' && a.pages">({{ a.pages }} pages · available for PDF tools)</small>
          <small v-if="a.state === 'ready' && a.rows">({{ a.rows.toLocaleString() }} rows, {{ a.columns }} columns)</small>
        </span>
        <button type="button" :aria-label="`Remove ${a.filename}`" @click="removeAttachment(a.id)">×</button>
      </li>
    </ul>
    <p v-if="draft === '' && suggestion && recallIndex === null" class="recall">Tab to use the suggestion</p>
    <p v-if="recallIndex !== null" class="recall" aria-live="polite">
      Earlier question {{ recallIndex + 1 }} of {{ history.length }} · ↑ older · ↓ newer
    </p>
    <div :class="['box', { dragging }]">
      <input ref="fileInput" type="file" multiple hidden @change="onPick" />
      <ListComposer
        v-if="listMode"
        ref="listEditor"
        v-model="draft"
        :initial-caret="initialListCaret"
        :placeholder="placeholder"
        @input="onInput"
        @keydown="onKeydown"
        @paste="onPaste"
      />
      <textarea
        v-else
        ref="textarea"
        v-model="draft"
        rows="1"
        :placeholder="placeholder"
        @input="onInput"
        @keydown="onKeydown"
        @paste="onPaste"
      />
      <div class="tools">
        <button v-if="auth.hasPermission('files.upload')" type="button" class="attach" title="Attach files (text, code, PDF, Word, Excel)" @click="fileInput?.click()">
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
        <!-- The chat page's own controls (settings, status) sit beside the attach button. -->
        <slot name="tools" />
        <span class="spacer" />
        <span class="send-slot">
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
          <!-- Outlives the Send button, which turns into Stop the moment a turn starts. -->
          <svg v-if="flights" :key="flights" class="plane" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" @animationend="flights = 0">
            <path d="M22 2 2 9.5l7.5 3L12.5 22z" fill="currentColor" />
          </svg>
        </span>
      </div>
    </div>
    <p class="keys">Enter to send · Shift+Enter for a new line or next list item</p>
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
  z-index: 16; /* above the settings menu (15) that sits over the composer */
  display: flex;
  flex-direction: column;
  max-height: 280px;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.15);
}
/* Only the options scroll; the key hint below stays put. */
.suggestions .options {
  position: relative; /* offsetParent of the rows, for the arrow-key scrolling */
  flex: 1;
  min-height: 0;
  margin: 0;
  padding: 4px;
  overflow-y: auto;
  list-style: none;
}
.suggestions li {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 10px;
  padding: 6px 10px;
  border-radius: var(--radius-md);
  cursor: pointer;
  font-size: 0.9em;
}
.suggestions li.active {
  /* --bg on the --surface popup is barely different; the accent tint is clearly visible in both themes. */
  background: color-mix(in srgb, var(--accent) 16%, transparent);
  box-shadow: inset 3px 0 var(--accent);
}
.suggestions code {
  font-family: var(--mono);
}
.suggestions span {
  color: var(--muted);
}
.suggestions .hint {
  flex: none;
  margin: 0;
  padding: 6px 14px;
  border-top: 1px solid var(--border);
  font-size: 0.75em;
  color: var(--muted);
}
.box {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 10px 8px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  background: var(--surface);
}
.box:focus-within {
  border-color: var(--accent);
}
/* A file is being dragged over: dashed and tinted, so it reads as a drop target and not as focus. */
.box.dragging {
  border-style: dashed;
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, var(--surface));
}
.tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-left: -6px;
}
.spacer {
  flex: 1;
}
.keys {
  margin: 6px 0 0;
  font-size: 0.75em;
  text-align: center;
  color: var(--muted);
}
@media (hover: none) {
  .keys {
    display: none;
  }
}
.attach {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
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
  border-radius: var(--radius-full);
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
  width: 100%;
  max-height: calc(1.55em * 5); /* 5 lines, then it scrolls */
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
  border-radius: var(--radius-full);
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
.send-slot {
  position: relative;
  display: grid;
  flex-shrink: 0;
}
.plane {
  position: absolute;
  top: 8px;
  left: 8px;
  pointer-events: none;
  color: var(--accent);
  animation: plane-fly 0.65s cubic-bezier(0.4, 0, 0.8, 0.6) forwards;
}
@keyframes plane-fly {
  0% {
    opacity: 1;
    transform: translate(0, 0) scale(1);
  }
  100% {
    opacity: 0;
    transform: translate(46px, -52px) scale(0.6);
  }
}
@media (prefers-reduced-motion: reduce) {
  .plane {
    display: none;
  }
}
</style>
