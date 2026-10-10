<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import EmIcon from "./EmIcon.vue";

/** A modal dialog the parent opens and closes with `open`. It is a native <dialog>
 * shown modally, so the browser traps focus, makes the page behind inert and returns
 * focus to the opener. It asks the parent to close (`close`) on Escape, on the close
 * button and on a click outside the panel. `danger` swaps the copper top rule for red. */
const props = defineProps<{ open: boolean; title: string; wide?: boolean; danger?: boolean }>();
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
  <dialog
    ref="dialog"
    class="em-dialog"
    :class="{ wide, danger }"
    :aria-label="title"
    @close="emit('close')"
    @cancel.prevent="emit('close')"
    @click="onClick"
  >
    <header class="head">
      <h2 class="em-pixel title">{{ title }}</h2>
      <button type="button" class="close" aria-label="Close" @click="emit('close')">
        <EmIcon name="close" />
      </button>
    </header>
    <slot />
  </dialog>
</template>

<style scoped>
.em-dialog {
  width: min(560px, calc(100vw - 32px));
  max-height: calc(100dvh - 48px);
  padding: 28px;
  overflow-y: auto;
  border: 1px solid var(--em-border);
  border-top: 3px solid var(--em-accent);
  border-radius: var(--em-radius);
  color: var(--em-text);
  background: var(--em-panel);
  box-shadow: var(--em-dialog-shadow);
  font-family: var(--em-font-body);
  font-size: 14px;
  line-height: 1.5;
}
.em-dialog.wide {
  width: min(1030px, calc(100vw - 32px));
}
.em-dialog.danger {
  border-top-color: var(--em-danger);
}
.em-dialog::backdrop {
  background: rgb(0 0 0 / 60%);
}
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--em-space-4);
  margin-bottom: 18px;
}
.title {
  margin: 0;
  font-size: 18px;
  line-height: 1.4;
}
.close {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: var(--em-target);
  height: var(--em-target);
  border: 1px solid var(--em-border);
  border-radius: var(--em-radius);
  color: var(--em-text);
  background: var(--em-raised);
  cursor: pointer;
}
.close:focus-visible {
  outline: 2px solid var(--em-accent);
  outline-offset: 3px;
}
@media (max-width: 700px) {
  .em-dialog {
    padding: 20px;
  }
  .title {
    font-size: 17px;
  }
}
</style>
