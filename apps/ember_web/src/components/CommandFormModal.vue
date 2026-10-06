<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import type { CommandInfo } from "../api/CommandsClient";
import type { JsonSchema } from "../api/types";
import { commandText } from "../utils/toolSchema";
import ToolRunForm from "./ToolRunForm.vue";

/** Fills a slash command's parameters from a form (port of chat_app's
 * command-form modal) instead of typing key=value by hand. Submitting
 * builds the same "/<capability> <command> key=value ..." text a user could
 * type, which the chat then runs. */

const props = defineProps<{ command: CommandInfo | null; schema: JsonSchema | null }>();
const emit = defineEmits<{ submit: [text: string]; close: [] }>();

const dialog = ref<HTMLDialogElement | null>(null);

watch(
  () => props.command && props.schema,
  async (open) => {
    await nextTick();
    if (open && !dialog.value?.open) dialog.value?.showModal();
    else if (!open && dialog.value?.open) dialog.value.close();
  },
);

function run(args: Record<string, unknown>): void {
  if (!props.command) return;
  emit("submit", commandText(props.command.capability, props.command.name, args));
}
</script>

<template>
  <dialog ref="dialog" class="command-form" @close="emit('close')" @cancel.prevent="emit('close')">
    <template v-if="command && schema">
      <header>
        <h3><code>/{{ command.capability }} {{ command.name }}</code></h3>
        <button type="button" class="close" aria-label="Close" @click="emit('close')">×</button>
      </header>
      <p v-if="command.description" class="description">{{ command.description }}</p>
      <ToolRunForm :key="command.tool_name" :schema="schema" :running="false" submit-label="Run command" @run="run" />
    </template>
  </dialog>
</template>

<style scoped>
.command-form {
  width: min(560px, calc(100vw - 32px));
  max-height: calc(100vh - 64px);
  padding: 18px 20px 20px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  color: var(--text);
  background: var(--surface);
}
.command-form::backdrop {
  background: rgb(0 0 0 / 45%);
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
h3 {
  margin: 0;
  font-size: 1em;
}
h3 code {
  font-family: var(--mono);
}
.close {
  border: none;
  background: none;
  cursor: pointer;
  font-size: 1.4em;
  line-height: 1;
  color: var(--muted);
}
.description {
  margin: 6px 0 14px;
  font-size: 0.9em;
  color: var(--muted);
}
</style>
