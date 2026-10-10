<script setup lang="ts">
/** A bordered steel panel with the page's hard bottom shadow. */
</script>

<template>
  <section class="em-panel"><slot /></section>
</template>

<style scoped>
.em-panel {
  padding: var(--em-space-5);
  border: 1px solid var(--em-border);
  border-radius: var(--em-radius);
  background: var(--em-panel);
  box-shadow: var(--em-panel-shadow);
}
@media (max-width: 700px) {
  .em-panel {
    padding: var(--em-space-4);
  }
}
</style>
