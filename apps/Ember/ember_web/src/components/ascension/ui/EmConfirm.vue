<script setup lang="ts">
import { computed, ref, watch } from "vue";
import EmButton from "./EmButton.vue";
import EmDialog from "./EmDialog.vue";

/** A confirmation dialog. With `requireText` the confirm button stays disabled until
 * that exact word is typed (the reset uses RESET). `danger` gives it the red rule and
 * the red button. The cancel button is named for what it keeps ("Keep battling"). The default
 * slot sits above the message, for a notice. */
const props = withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    message: string;
    confirmLabel: string;
    cancelLabel?: string;
    requireText?: string;
    danger?: boolean;
    busy?: boolean;
  }>(),
  { cancelLabel: "Cancel", requireText: undefined, danger: false, busy: false },
);
const emit = defineEmits<{ confirm: []; close: [] }>();

const typed = ref("");
const ready = computed(() => (props.requireText === undefined || typed.value === props.requireText) && !props.busy);

watch(
  () => props.open,
  () => {
    typed.value = "";
  },
);
</script>

<template>
  <EmDialog :open="open" :title="title" :danger="danger" @close="emit('close')">
    <slot />
    <p class="message">{{ message }}</p>
    <label v-if="requireText !== undefined" class="require">
      <span>Type {{ requireText }} to confirm</span>
      <input v-model="typed" class="field" type="text" autocomplete="off" spellcheck="false" />
    </label>
    <div class="actions">
      <EmButton @click="emit('close')">{{ cancelLabel }}</EmButton>
      <EmButton class="confirm" :variant="danger ? 'danger' : 'primary'" :disabled="!ready" @click="emit('confirm')">
        {{ confirmLabel }}
      </EmButton>
    </div>
  </EmDialog>
</template>

<style scoped>
.message {
  margin: 0 0 18px;
  color: var(--em-muted);
}
.require {
  display: flex;
  flex-direction: column;
  gap: var(--em-space-2);
  margin-bottom: 18px;
  font-size: 12px;
  font-weight: 600;
  color: var(--em-muted);
}
.field {
  min-height: var(--em-target);
  padding: 10px 12px;
  border: 1px solid var(--em-border);
  border-radius: var(--em-radius);
  color: var(--em-text);
  background: var(--em-bg);
  font: inherit;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--em-space-3);
}
</style>
