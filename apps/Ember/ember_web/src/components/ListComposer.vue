<script setup lang="ts">
import { onBeforeUnmount, onMounted, watch } from "vue";
import { EditorContent, useEditor } from "@tiptap/vue-3";
import StarterKit from "@tiptap/starter-kit";
import { composerFenceOpen, parseComposer, serializeComposer } from "../utils/composerLists";

const props = defineProps<{ modelValue: string; placeholder: string; initialCaret?: number }>();
const emit = defineEmits<{
  "update:modelValue": [value: string];
  input: [];
  keydown: [event: KeyboardEvent];
  paste: [event: ClipboardEvent];
}>();

const editor = useEditor({
  extensions: [StarterKit.configure({
    bold: false, italic: false, underline: false, strike: false, code: false,
    codeBlock: false, heading: false, horizontalRule: false, blockquote: false, link: false,
    trailingNode: false,
  })],
  content: parseComposer(props.modelValue),
  enableInputRules: ["bulletList", "orderedList"],
  editorProps: {
    attributes: {
      role: "textbox", "aria-multiline": "true", "aria-label": "Message",
      "data-placeholder": props.placeholder, placeholder: props.placeholder,
      class: "list-composer",
    },
    handleKeyDown: (_view, event) => {
      emit("keydown", event);
      if (event.defaultPrevented) return true;
      if (event.isComposing) return false;
      const current = editor.value;
      if (!current) return false;
      if (event.key === "Enter" && event.shiftKey) {
        event.preventDefault();
        if (!current.commands.splitListItem("listItem") && !current.commands.liftListItem("listItem")) {
          current.commands.splitBlock();
        }
        return true;
      }
      if (event.key === "Tab" && current.isActive("listItem")) {
        const changed = event.shiftKey ? current.commands.liftListItem("listItem") : current.commands.sinkListItem("listItem");
        if (changed) { event.preventDefault(); return true; }
      }
      return false;
    },
    handlePaste: (_view, event) => {
      emit("paste", event);
      if (event.defaultPrevented) return true;
      const text = event.clipboardData?.getData("text/plain");
      if (text === undefined) return false;
      // Accept text, never the clipboard's arbitrary HTML or embedded styles.
      editor.value?.commands.insertContent(parseComposer(text).content ?? []);
      return true;
    },
    handleTextInput: (view, from, to, text) => {
      if (!composerFenceOpen(view.state.doc.textBetween(0, from, "\n"))) return false;
      // Keep list input rules from reformatting literal examples inside fences.
      view.dispatch(view.state.tr.insertText(text, from, to));
      return true;
    },
  },
  onUpdate: ({ editor: current }) => {
    emit("update:modelValue", serializeComposer(current.getJSON()));
    emit("input");
  },
});

watch(() => props.modelValue, (value) => {
  const current = editor.value;
  if (current && value !== serializeComposer(current.getJSON())) {
    current.commands.setContent(parseComposer(value), { emitUpdate: false });
  }
});
watch(() => props.placeholder, (placeholder) => {
  editor.value?.setOptions({ editorProps: { attributes: {
    role: "textbox", "aria-multiline": "true", "aria-label": "Message",
    "data-placeholder": placeholder, placeholder, class: "list-composer",
  } } });
});

function focus(): void { editor.value?.commands.focus(); }
function focusEnd(): void { editor.value?.commands.focus("end"); }
function atHistoryEdge(up: boolean): boolean {
  const state = editor.value?.state;
  if (!state) return false;
  const text = up ? state.doc.textBetween(0, state.selection.from, "\n") : state.doc.textBetween(state.selection.to, state.doc.content.size, "\n");
  return !text.includes("\n");
}
defineExpose({ focus, focusEnd, atHistoryEdge });
onMounted(() => {
  const current = editor.value;
  if (!current || props.initialCaret === undefined) { focusEnd(); return; }
  const source = props.modelValue.split("\n");
  const before = props.modelValue.slice(0, props.initialCaret).split("\n");
  const targetLine = before.length - 1;
  const prefix = /^( *)([-+*]|\d+[.)]) /.exec(source[targetLine] ?? "")?.[0].length ?? 0;
  const column = Math.max(0, before.at(-1)!.length - prefix);
  let line = 0;
  let position = current.state.doc.content.size - 1;
  current.state.doc.descendants((node, pos) => {
    if (node.type.name !== "paragraph") return;
    const rows = node.textBetween(0, node.content.size, "\n", "\n").split("\n");
    if (targetLine >= line && targetLine < line + rows.length) {
      const row = targetLine - line;
      const offset = rows.slice(0, row).reduce((sum, text) => sum + text.length + 1, 0);
      position = pos + 1 + offset + Math.min(column, rows[row]!.length);
    }
    line += rows.length;
  });
  current.commands.focus(position);
});
onBeforeUnmount(() => editor.value?.destroy());
</script>

<template><EditorContent :editor="editor" /></template>

<style scoped>
:deep(.list-composer) {
  width: 100%;
  max-height: calc(1.55em * 5);
  overflow-y: auto;
  overflow-wrap: anywhere;
  padding: 6px 0;
  outline: none;
  white-space: pre-wrap;
  font: inherit;
  color: inherit;
}
:deep(.list-composer p) { margin: 0; }
:deep(.list-composer ul), :deep(.list-composer ol) { margin: 0; padding-left: 1.4em; }
:deep(.list-composer ul) { list-style-type: disc; }
:deep(.list-composer ol) { list-style-type: decimal; }
:deep(.list-composer p.is-editor-empty:first-child::before) {
  content: attr(data-placeholder);
  color: var(--muted);
  pointer-events: none;
}
@media (max-width: 767px) { :deep(.list-composer) { font-size: max(1em, 16px); } }
</style>
