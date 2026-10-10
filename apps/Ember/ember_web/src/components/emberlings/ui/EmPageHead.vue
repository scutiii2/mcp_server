<script setup lang="ts">
/** The title block at the top of a screen: copper eyebrow, pixel title, a line under it,
 * and a slot on the right for navigation. */
defineProps<{ title: string; subtitle?: string; eyebrow?: string }>();
</script>

<template>
  <div class="head">
    <div>
      <p class="em-eyebrow">{{ eyebrow ?? "The forge is yours" }}</p>
      <h2 class="em-pixel title">{{ title }}</h2>
      <p v-if="subtitle" class="subtitle">{{ subtitle }}</p>
    </div>
    <div class="side"><slot /></div>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--em-space-4);
  margin-bottom: var(--em-space-5);
}
.title {
  margin: 8px 0 4px;
  font-size: 28px;
  line-height: 1.3;
}
.subtitle {
  color: var(--em-muted);
}
.side {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--em-space-4);
}
@media (max-width: 700px) {
  .title {
    font-size: 23px;
  }
  .side {
    width: 100%;
  }
}
</style>
