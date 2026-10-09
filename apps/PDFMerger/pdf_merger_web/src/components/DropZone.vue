<script setup lang="ts">
// Drop target and file picker. Type checks happen on the server (magic bytes),
// so `accept` here only narrows the picker.
import { ref } from 'vue'

const emit = defineEmits<{ files: [File[]] }>()
const over = ref(false)
const input = ref<HTMLInputElement | null>(null)

function onDrop(event: DragEvent): void {
  over.value = false
  const list = Array.from(event.dataTransfer?.files ?? [])
  if (list.length) emit('files', list)
}

function onPick(event: Event): void {
  const element = event.target as HTMLInputElement
  const list = Array.from(element.files ?? [])
  element.value = ''
  if (list.length) emit('files', list)
}
</script>

<template>
  <div
    class="dropzone"
    :class="{ over }"
    role="button"
    tabindex="0"
    aria-label="Add files"
    @click="input?.click()"
    @keydown.enter.prevent="input?.click()"
    @keydown.space.prevent="input?.click()"
    @dragover.prevent="over = true"
    @dragleave="over = false"
    @drop.prevent="onDrop"
  >
    <p class="dropzone-title">Drop PDFs or images here</p>
    <p class="muted small">PDF, JPG, PNG, WebP, TIFF, GIF or HEIC · up to 100 MB each · or click to choose</p>
    <input ref="input" type="file" multiple hidden accept=".pdf,image/*,.heic,.heif" @change="onPick" />
  </div>
</template>
