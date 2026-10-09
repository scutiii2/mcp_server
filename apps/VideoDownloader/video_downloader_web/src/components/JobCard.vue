<script setup lang="ts">
import { computed } from 'vue'
import { formatEta, formatSpeed } from '../lib/format'
import type { JobView } from '../stores/jobs'

const props = defineProps<{ job: JobView }>()
defineEmits<{ cancel: []; dismiss: [] }>()

const running = computed(() => ['queued', 'downloading', 'processing'].includes(props.job.state))
const stateText = computed(() => {
  switch (props.job.state) {
    case 'queued':
      return 'Waiting in line...'
    case 'processing':
      return 'Processing (merging and converting)...'
    case 'downloading':
      return `${Math.round(props.job.percent ?? 0)}%`
    case 'done':
      return 'Done'
    default:
      return ''
  }
})
</script>

<template>
  <li class="panel">
    <div class="row">
      <div class="grow">
        <div class="name">{{ job.title }} <span class="muted small">{{ job.presetLabel }}</span></div>
        <div v-if="job.state !== 'error'" class="muted small">
          {{ stateText }}
          <template v-if="job.state === 'downloading'">
            <span v-if="job.speed !== null"> &middot; {{ formatSpeed(job.speed) }}</span>
            <span v-if="job.eta !== null"> &middot; {{ formatEta(job.eta) }} left</span>
          </template>
        </div>
        <div v-else class="error small">{{ job.error?.message }}</div>
      </div>
      <button v-if="running && job.state !== 'processing'" class="cancel" type="button" @click="$emit('cancel')">Cancel</button>
      <a v-if="job.state === 'done' && job.file" class="primary" :href="job.file.download_url" download>Download file</a>
      <button v-if="!running" class="dismiss" type="button" @click="$emit('dismiss')">Dismiss</button>
    </div>
    <progress v-if="running" max="100" :value="job.state === 'processing' ? 100 : (job.percent ?? 0)"></progress>
  </li>
</template>
