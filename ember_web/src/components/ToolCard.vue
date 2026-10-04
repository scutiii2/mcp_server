<script setup lang="ts">
import type { ToolInfo } from "../api/types";
import IconTile from "./IconTile.vue";

/** One mcp_server tool as a tile: an icon, its label and its tool name. A click
 * asks the parent to open its details and run form (a modal). */
defineProps<{ tool: ToolInfo; icon: string[] }>();
const emit = defineEmits<{ open: [] }>();
</script>

<template>
  <li class="tool">
    <IconTile :label="tool.title" :subtitle="tool.name" :description="tool.description" :icon="icon" aria-haspopup="dialog" @click="emit('open')" />
  </li>
</template>

<style scoped>
.tool {
  display: flex;
}
.tool > :deep(.tile) {
  flex: 1;
}
</style>
