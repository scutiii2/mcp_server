<script setup lang="ts">
// Centered card shell shared by the login / register / verify pages.
defineProps<{ title: string; subtitle?: string }>();
</script>

<template>
  <section class="auth-page">
    <div class="card">
      <h1>{{ title }}</h1>
      <p v-if="subtitle" class="subtitle">{{ subtitle }}</p>
      <slot />
      <footer v-if="$slots.footer" class="footer"><slot name="footer" /></footer>
    </div>
  </section>
</template>

<style scoped>
.auth-page {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: grid;
  place-items: center;
  padding: 24px 16px;
}
.card {
  width: 100%;
  max-width: 380px;
  padding: 28px 24px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface);
}
h1 {
  margin: 0 0 4px;
  font-size: 1.35em;
}
.subtitle {
  margin: 0 0 20px;
  color: var(--muted);
}
.footer {
  margin-top: 18px;
  font-size: 0.9em;
  color: var(--muted);
  text-align: center;
}
/* Form styling for whatever the page slots in. */
.card :deep(form) {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.card :deep(label) {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.9em;
  font-weight: 600;
}
.card :deep(input) {
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-weight: normal;
  background: var(--bg);
}
.card :deep(input:focus) {
  outline: none;
  border-color: var(--accent);
}
.card :deep(.primary) {
  margin-top: 4px;
  padding: 9px 16px;
  border: none;
  border-radius: 999px;
  cursor: pointer;
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.card :deep(.primary:disabled) {
  cursor: default;
  opacity: 0.5;
}
.card :deep(.link-button) {
  padding: 0;
  border: none;
  cursor: pointer;
  color: var(--accent);
  background: none;
  text-decoration: underline;
}
.card :deep(.error) {
  margin: 0;
  color: var(--danger);
}
.card :deep(.notice) {
  margin: 0;
  color: var(--muted);
}
</style>
