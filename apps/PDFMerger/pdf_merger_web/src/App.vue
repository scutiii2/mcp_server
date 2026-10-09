<script setup lang="ts">
import { onMounted } from 'vue'
import DropZone from './components/DropZone.vue'
import MergeBar from './components/MergeBar.vue'
import OutputPanel from './components/OutputPanel.vue'
import PageStrip from './components/PageStrip.vue'
import SourceList from './components/SourceList.vue'
import { useFilesStore } from './stores/files'
import { usePlanStore } from './stores/plan'

const files = useFilesStore()
usePlanStore() // created here so its page watcher runs from the start

onMounted(() => {
  void files.restore()
})
</script>

<template>
  <main class="app">
    <header class="app-head">
      <h1>PDF merger</h1>
      <span class="muted small">Files are kept for 6 hours</span>
    </header>
    <DropZone @files="files.upload($event)" />
    <p v-if="files.uploading" class="muted small" aria-live="polite">Uploading {{ files.uploading }} file(s)…</p>
    <ul v-if="files.errors.length" class="errors">
      <li v-for="(message, index) in files.errors" :key="index" role="alert">
        {{ message }}
        <button type="button" class="link" @click="files.dismissError(index)">Dismiss</button>
      </li>
    </ul>
    <SourceList />
    <PageStrip />
    <OutputPanel />
    <MergeBar />
  </main>
</template>
