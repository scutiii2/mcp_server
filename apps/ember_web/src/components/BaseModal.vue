<script setup lang="ts">
import { nextTick, ref, watch } from "vue";

/** A modal dialog the parent opens and closes with `open`. It closes itself on
 * Escape, on the × and on a click outside the panel, by asking the parent
 * (`close`) rather than hiding on its own. The default slot is the body. */
const props = defineProps<{ open: boolean; title: string }>();
const emit = defineEmits<{ close: [] }>();

const dialog = ref<HTMLDialogElement | null>(null);

watch(
  () => props.open,
  async (isOpen) => {
    await nextTick();
    if (isOpen && !dialog.value?.open) dialog.value?.showModal();
    else if (!isOpen && dialog.value?.open) dialog.value.close();
  },
  { immediate: true },
);

/** A click on the backdrop lands on the <dialog> itself, not on its content. */
function onClick(event: MouseEvent): void {
  if (event.target === dialog.value) emit("close");
}
</script>

<template>
  <dialog ref="dialog" class="modal" :aria-label="title" @close="emit('close')" @cancel.prevent="emit('close')" @click="onClick">
    <header>
      <h3>{{ title }}</h3>
      <button type="button" class="close" aria-label="Close" @click="emit('close')">×</button>
    </header>
    <slot />
  </dialog>
</template>

<style scoped>
.modal {
  width: min(560px, calc(100vw - 32px));
  max-height: calc(100vh - 64px);
  padding: 18px 20px 20px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 14px;
  color: var(--text);
  background: var(--surface);
}
.modal::backdrop {
  background: rgb(0 0 0 / 45%);
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
h3 {
  margin: 0;
  font-size: 1em;
}
.close {
  border: none;
  background: none;
  cursor: pointer;
  font-size: 1.4em;
  line-height: 1;
  color: var(--muted);
}
</style>
