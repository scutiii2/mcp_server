<script setup lang="ts">
// Merge summary, progress, result and the merge button.
import { computed, ref } from 'vue'
import { formatBytes, plural } from '../lib/format'
import { usePlanStore } from '../stores/plan'

const plan = usePlanStore()
const copied = ref(false)

const summary = computed(() => {
  const fileCount = new Set(plan.pages.map((p) => p.fileId)).size
  return `${plural(plan.pages.length, 'page')} from ${plural(fileCount, 'file')}`
})
const percent = computed(() =>
  plan.progress.total ? Math.round((plan.progress.done / plan.progress.total) * 100) : 0,
)
// The server's link is absolute (public_base_url); keep only path + query so it
// goes through this app's /api proxy, whatever host the browser used.
const downloadHref = computed(() => {
  if (!plan.result) return ''
  const url = new URL(plan.result.download_url, window.location.href)
  return `${url.pathname}${url.search}`
})

async function copyId(): Promise<void> {
  if (!plan.result) return
  try {
    await navigator.clipboard.writeText(plan.result.file_id)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    // Clipboard blocked; the ID is shown in the button title.
  }
}
</script>

<template>
  <div class="merge-bar">
    <div class="status" aria-live="polite">
      <template v-if="plan.status === 'running'">
        Merging… {{ plan.progress.done }} of {{ plan.progress.total }} pages
        <progress :value="percent" max="100" />
      </template>
      <template v-else-if="plan.status === 'done' && plan.result">
        Done · {{ plan.result.name }} ({{ formatBytes(plan.result.size) }})
        <a :href="downloadHref" download>Download</a>
        <button type="button" class="link" :title="plan.result.file_id" @click="copyId">
          {{ copied ? 'Copied' : 'Copy ID' }}
        </button>
      </template>
      <span v-else-if="plan.status === 'error'" class="error" role="alert">{{ plan.error }}</span>
      <span v-else-if="plan.hasRangeErrors" class="error">Fix the page ranges marked in red, then merge.</span>
      <template v-else-if="plan.pages.length">Ready to merge {{ summary }}</template>
      <template v-else>Add files to start</template>
    </div>
    <button type="button" class="primary" :disabled="!plan.canMerge" @click="plan.merge()">
      {{ plan.status === 'running' ? 'Merging…' : 'Merge' }}
    </button>
  </div>
</template>
