<script setup lang="ts">
import BaseModal from "../BaseModal.vue";

/** Asks the user to confirm an action, in place of the browser's confirm().
 * The parent keeps `open`, runs the action on `confirm` and closes on `close`
 * (which also fires for Escape, the × and a click outside). `busy` disables the
 * buttons while the action runs. */
withDefaults(
  defineProps<{ open: boolean; title: string; message: string; confirmLabel?: string; danger?: boolean; busy?: boolean }>(),
  { confirmLabel: "Confirm", danger: false, busy: false },
);
const emit = defineEmits<{ confirm: []; close: [] }>();
</script>

<template>
  <BaseModal :open="open" :title="title" @close="emit('close')">
    <p class="message">{{ message }}</p>
    <div class="actions">
      <button type="button" class="cancel" :disabled="busy" @click="emit('close')">Cancel</button>
      <button type="button" :class="['confirm', { danger }]" :disabled="busy" @click="emit('confirm')">
        {{ confirmLabel }}
      </button>
    </div>
  </BaseModal>
</template>

<style scoped>
.message {
  margin: 0 0 16px;
  overflow-wrap: anywhere;
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
button {
  padding: 6px 16px;
  border-radius: 999px;
  cursor: pointer;
  font: inherit;
}
button:disabled {
  cursor: default;
  opacity: 0.5;
}
.cancel {
  border: 1px solid var(--border);
  color: var(--text);
  background: transparent;
}
.confirm {
  border: none;
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.confirm.danger {
  border: 1px solid var(--danger);
  color: var(--danger);
  background: transparent;
}
</style>
