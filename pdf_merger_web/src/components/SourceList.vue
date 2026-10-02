<script setup lang="ts">
// Source files in default order; drag a row to reorder.
import { ref } from 'vue'
import { useFilesStore } from '../stores/files'
import SourceRow from './SourceRow.vue'

const files = useFilesStore()
const dragFrom = ref<number | null>(null)

function onDrop(index: number): void {
  if (dragFrom.value !== null) files.moveSource(dragFrom.value, index)
  dragFrom.value = null
}
</script>

<template>
  <section v-if="files.sources.length" class="panel">
    <h2>Source files</h2>
    <ol class="source-list">
      <li
        v-for="(source, index) in files.sources"
        :key="source.info.file_id"
        draggable="true"
        :class="{ dragging: dragFrom === index }"
        @dragstart="dragFrom = index"
        @dragend="dragFrom = null"
        @dragover.prevent
        @drop.prevent="onDrop(index)"
      >
        <SourceRow
          :source="source"
          @range="files.setRange(source.info.file_id, $event)"
          @rotate="files.rotate(source.info.file_id)"
          @fit="files.setFit(source.info.file_id, $event)"
          @remove="files.remove(source.info.file_id)"
        />
      </li>
    </ol>
  </section>
</template>
