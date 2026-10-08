<script setup lang="ts">
import { computed, ref, watch } from "vue";
import BaseModal from "../BaseModal.vue";
import DeleteButton from "../DeleteButton.vue";

/** Asks the user to confirm an action, in place of the browser's confirm().
 * The parent keeps `open`, runs the action on `confirm` and closes on `close`
 * (which also fires for Escape, the × and a click outside). `busy` disables the
 * buttons while the action runs. `requireText` raises the friction for a severe
 * action: the confirm button stays disabled until that exact text is typed. */
const props = withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    message: string;
    confirmLabel?: string;
    danger?: boolean;
    busy?: boolean;
    requireText?: string;
  }>(),
  { confirmLabel: "Confirm", danger: false, busy: false, requireText: "" },
);
const emit = defineEmits<{ confirm: []; close: [] }>();

const typed = ref("");
const matches = computed(() => props.requireText === "" || typed.value === props.requireText);

watch(
  () => props.open,
  () => {
    typed.value = "";
  },
);

function confirm(): void {
  if (matches.value && !props.busy) emit("confirm");
}
</script>

<template>
  <BaseModal :open="open" :title="title" @close="emit('close')">
    <p class="message">{{ message }}</p>
    <label v-if="requireText" class="require">
      <span>
        Type <code>{{ requireText }}</code> to confirm
      </span>
      <!-- autofocus: showModal() focuses it, so typing starts at once. -->
      <input
        v-model="typed"
        type="text"
        autofocus
        autocomplete="off"
        spellcheck="false"
        :disabled="busy"
        @keydown.enter.prevent="confirm"
      />
      <span class="count" aria-hidden="true">{{ typed.length }}/{{ requireText.length }}</span>
    </label>
    <div class="actions">
      <button type="button" class="cancel" :disabled="busy" @click="emit('close')">Cancel</button>
      <DeleteButton
        v-if="danger"
        class="confirm danger"
        :label="confirmLabel"
        :busy="busy"
        :disabled="!matches"
        @click="confirm"
      />
      <button v-else type="button" class="confirm" :disabled="busy || !matches" @click="confirm">
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
.require {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0 0 16px;
  font-size: 0.9em;
}
.require code {
  font-family: var(--mono);
  overflow-wrap: anywhere;
}
.require input {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
}
.require input:focus {
  outline: none;
  border-color: var(--accent);
}
.count {
  align-self: flex-end;
  font-family: var(--mono);
  font-size: 0.8em;
  color: var(--muted);
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
button {
  padding: 6px 16px;
  border-radius: var(--radius-full);
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
.confirm:not(.danger) {
  border: none;
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
</style>
