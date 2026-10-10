<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import EmIcon from "./EmIcon.vue";

/** A short confirmation ("Preset 1 saved"). It asks to be closed after about four
 * seconds, and not while the pointer or the keyboard focus is on it. */
const props = withDefaults(defineProps<{ open: boolean; message: string; duration?: number }>(), { duration: 4000 });
const emit = defineEmits<{ close: [] }>();

const held = ref(false);
let timer: ReturnType<typeof setTimeout> | null = null;

function clear(): void {
  if (timer !== null) clearTimeout(timer);
  timer = null;
}

function arm(): void {
  clear();
  if (props.open && !held.value) timer = setTimeout(() => emit("close"), props.duration);
}

watch(() => [props.open, held.value], arm, { immediate: true });
onBeforeUnmount(clear);
</script>

<template>
  <div class="em-toast-region" role="status" aria-live="polite">
    <div v-if="open" class="em-toast" tabindex="0" @mouseenter="held = true" @mouseleave="held = false" @focus="held = true" @blur="held = false">
      <EmIcon name="check" />
      <span>{{ message }}</span>
    </div>
  </div>
</template>

<style scoped>
.em-toast-region {
  display: flex;
  justify-content: flex-end;
}
.em-toast {
  display: flex;
  align-items: center;
  gap: 10px;
  max-width: 420px;
  padding: 12px 16px;
  border: 1px solid var(--em-success);
  border-radius: var(--em-radius);
  color: var(--em-success);
  background: var(--em-success-surface);
}
@media (max-width: 700px) {
  .em-toast-region {
    justify-content: stretch;
  }
  .em-toast {
    max-width: none;
    font-size: 12px;
  }
}
</style>
