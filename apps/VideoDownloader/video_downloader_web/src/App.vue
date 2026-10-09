<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import FileRow from './components/FileRow.vue'
import JobCard from './components/JobCard.vue'
import ProbeCard from './components/ProbeCard.vue'
import UrlBar from './components/UrlBar.vue'
import { plural } from './lib/format'
import { useFilesStore } from './stores/files'
import { useJobsStore } from './stores/jobs'
import { useProbeStore } from './stores/probe'

const probe = useProbeStore()
const jobs = useJobsStore()
const files = useFilesStore()

const now = ref(Date.now() / 1000)
let timer: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  void files.refresh()
  timer = setInterval(() => (now.value = Date.now() / 1000), 30_000)
})
onBeforeUnmount(() => clearInterval(timer))

async function download(): Promise<void> {
  const result = probe.result
  const option = probe.selectedOption
  if (!result || !option) return
  await jobs.start(result.url, result.title, option)
  if (!jobs.startError) probe.reset()
}
</script>

<template>
  <main class="app">
    <header class="app-head">
      <h1>Video downloader</h1>
      <span class="muted small">{{ plural(files.files.length, 'file') }} kept for a few hours</span>
    </header>

    <UrlBar v-model="probe.url" :loading="probe.loading" :can-check="probe.canCheck" @check="probe.check()" />
    <p v-if="probe.error" class="error" role="alert">{{ probe.error }}</p>
    <p v-if="jobs.startError" class="error" role="alert">{{ jobs.startError }}</p>

    <ProbeCard v-if="probe.result" :result="probe.result" :selected="probe.selected" @select="probe.select($event)" @download="download" />

    <section v-if="jobs.jobs.length">
      <h2>Downloads</h2>
      <ul class="list">
        <JobCard v-for="job in jobs.jobs" :key="job.id" :job="job" @cancel="jobs.cancel(job.id)" @dismiss="jobs.dismiss(job.id)" />
      </ul>
    </section>

    <section class="panel">
      <h2>My files</h2>
      <p v-if="files.error" class="error" role="alert">{{ files.error }}</p>
      <p v-if="!files.files.length" class="muted small">Nothing here yet. Finished downloads show up here until they expire.</p>
      <ul v-else class="list">
        <FileRow v-for="file in files.files" :key="file.file_id" :file="file" :now="now" @remove="files.remove(file.file_id)" />
      </ul>
    </section>

    <p class="footer muted small">Download only content you have the right to download.</p>
  </main>
</template>
