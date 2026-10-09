<script setup lang="ts">
defineProps<{ modelValue: string; loading: boolean; canCheck: boolean }>()
defineEmits<{ 'update:modelValue': [value: string]; check: [] }>()
</script>

<template>
  <form class="url-bar" @submit.prevent="$emit('check')">
    <input
      type="url"
      :value="modelValue"
      placeholder="Paste a video link (YouTube, TikTok, ...)"
      aria-label="Video link"
      autofocus
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
    <button class="primary" type="submit" :disabled="!canCheck">{{ loading ? 'Checking...' : 'Check' }}</button>
  </form>
</template>
