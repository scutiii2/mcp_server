<script setup lang="ts">
import { useAuthStore } from "../stores/auth";
import type { DownloadCard } from "../utils/downloads";
import { formatFileSize } from "../utils/downloads";

const auth = useAuthStore();

defineProps<{ downloads: DownloadCard[] }>();

function size(card: DownloadCard): string {
  const text = formatFileSize(card.bytes);
  return text ? ` (${text})` : "";
}
</script>

<template>
  <div v-if="downloads.length" class="downloads">
    <div v-for="(card, i) in downloads" :key="i" class="card">
      <div class="tag">{{ card.label }}</div>
      <a v-if="card.href && auth.hasPermission('files.download')" class="file" :href="card.href" download>⬇ Download {{ card.filename }}{{ size(card) }}</a>
      <span v-else class="file unavailable" title="This file cannot be downloaded from here">
        {{ card.filename }}{{ size(card) }} (unavailable)
      </span>
    </div>
  </div>
</template>

<style scoped>
.downloads {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}
.tag {
  font-size: 0.7em;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin-bottom: 3px;
}
.file {
  display: inline-block;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--code-bg);
  color: var(--text);
  font-size: 0.9em;
  text-decoration: none;
}
a.file:hover {
  border-color: var(--accent);
}
.unavailable {
  color: var(--muted);
}
</style>
