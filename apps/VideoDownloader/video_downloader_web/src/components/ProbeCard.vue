<script setup lang="ts">
import { computed } from 'vue'
import type { ProbeResult } from '../api/types'
import { formatBytes, formatDuration } from '../lib/format'

const props = defineProps<{ result: ProbeResult; selected: string | null }>()
defineEmits<{ select: [id: string]; download: [] }>()

// The thumbnail URL comes from the remote site: load it only over https (no mixed content, no plain-http tracking).
const thumbnail = computed(() => (props.result.thumbnail?.startsWith('https://') ? props.result.thumbnail : null))
</script>

<template>
  <section class="panel probe">
    <img v-if="thumbnail" :src="thumbnail" alt="" />
    <div v-else class="muted small">No preview</div>
    <div>
      <div class="title">{{ result.title }}</div>
      <div class="muted small">
        <span v-if="result.uploader">{{ result.uploader }}</span>
        <span v-if="result.uploader && result.duration !== null"> &middot; </span>
        <span v-if="result.duration !== null">{{ formatDuration(result.duration) }}</span>
      </div>
      <ul class="presets">
        <li v-for="option in result.options" :key="option.id">
          <label class="preset" :class="{ selected: option.id === selected, blocked: option.blocked }">
            <input
              type="radio"
              name="preset"
              :value="option.id"
              :checked="option.id === selected"
              :disabled="option.blocked"
              @change="$emit('select', option.id)"
            />
            {{ option.label }}
            <span v-if="option.estimated_bytes !== null" class="muted small">~{{ formatBytes(option.estimated_bytes) }}</span>
            <span v-if="option.blocked && option.reason" class="error small">{{ option.reason }}</span>
          </label>
        </li>
      </ul>
      <button class="primary" type="button" :disabled="selected === null" @click="$emit('download')">Download</button>
    </div>
  </section>
</template>
