<script setup lang="ts">
import type { FileInfo } from '../api/types'
import { formatBytes, formatDuration, formatExpiry } from '../lib/format'

defineProps<{ file: FileInfo; now: number }>()
defineEmits<{ remove: [] }>()
</script>

<template>
  <li class="row">
    <span class="kind" :class="file.kind">{{ file.kind }}</span>
    <div class="grow">
      <div class="name" :title="file.name">{{ file.name }}</div>
      <div class="muted small">
        {{ formatBytes(file.size) }}
        <span v-if="file.duration !== null"> &middot; {{ formatDuration(file.duration) }}</span>
        &middot; expires in {{ formatExpiry(file.expires_at, now) }}
      </div>
    </div>
    <a :href="file.download_url" download>Download</a>
    <button class="remove" type="button" @click="$emit('remove')">Delete</button>
  </li>
</template>
