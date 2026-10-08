<script setup lang="ts">
import MarkdownContent from "./MarkdownContent.vue";
defineProps<{ reading: string | null; uri: string; readResult: { uri: string; text: string } | null; readError: string; text: string }>();
const emit = defineEmits<{ 'update:uri': [value: string]; read: [uri: string] }>();
</script>
<template>
  <section v-if="reading || readResult || readError" class="reader">
    <form v-if="reading" class="uri" @submit.prevent="emit('read', uri)">
      <label>
        URI
        <input :value="uri" @input="emit('update:uri', ($event.target as HTMLInputElement).value)" type="text" spellcheck="false" />
      </label>
      <button class="primary">Read</button>
    </form>
    <p v-if="readError" class="error">{{ readError }}</p>
    <template v-if="readResult">
      <h3><code>{{ readResult.uri }}</code></h3>
      <MarkdownContent :text="text" />
    </template>
  </section>
</template>
<style scoped>
.reader {
  margin-top: 16px;
  padding: 12px 14px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-lg);
}
.uri {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 8px;
  margin-bottom: 10px;
}
.uri label {
  display: grid;
  flex: 1 1 260px;
  gap: 4px;
  font-size: 0.85em;
}
.uri input {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
  font-family: var(--mono);
}
.primary {
  padding: 6px 16px;
  border: none;
  border-radius: var(--radius-full);
  cursor: pointer;
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.error { color: var(--danger); }
</style>
