<script setup lang="ts">
// Every output page in order. Dragging a page switches the plan to manual order.
import { computed, ref } from 'vue'
import { plural } from '../lib/format'
import { useFilesStore } from '../stores/files'
import { usePlanStore } from '../stores/plan'
import PageThumb from './PageThumb.vue'

const files = useFilesStore()
const plan = usePlanStore()
const dragFrom = ref<number | null>(null)
const infoById = computed(() => new Map(files.sources.map((s) => [s.info.file_id, s.info])))

function label(fileId: string, page: number): string {
  const info = infoById.value.get(fileId)
  if (!info) return ''
  const name = info.name.replace(/\.[^.]+$/, '')
  return info.kind === 'image' ? name : `${name} p${page + 1}`
}

function onDragStart(index: number, event: DragEvent): void {
  dragFrom.value = index
  if (event.dataTransfer) {
    event.dataTransfer.setData('text/plain', String(index))
    event.dataTransfer.effectAllowed = 'move'
  }
}

function onDragOver(event: DragEvent): void {
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
}

function onKey(index: number, event: KeyboardEvent): void {
  if (!event.altKey || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return
  event.preventDefault()
  const to = event.key === 'ArrowLeft' ? index - 1 : index + 1
  if (to >= 0 && to < plan.pages.length) plan.movePage(index, to)
}

function onDrop(index: number): void {
  if (dragFrom.value !== null) plan.movePage(dragFrom.value, index)
  dragFrom.value = null
}
</script>

<template>
  <section v-if="plan.pages.length" class="panel">
    <div class="panel-head">
      <h2>Pages <span class="muted small">drag to reorder</span></h2>
      <span class="muted small">{{ plural(plan.pages.length, 'page') }}</span>
      <button v-if="plan.manualOrder" type="button" class="link" @click="plan.resetOrder()">Reset order</button>
    </div>
    <ol class="strip" aria-label="Pages. Press Alt and an arrow key to move a page.">
      <li
        v-for="(item, index) in plan.pages"
        :key="item.key"
        draggable="true"
        tabindex="0"
        :class="{ dragging: dragFrom === index }"
        @dragstart="onDragStart(index, $event)"
        @dragend="dragFrom = null"
        @keydown="onKey(index, $event)"
        @dragover.prevent="onDragOver"
        @drop.prevent="onDrop(index)"
      >
        <PageThumb :item="item" :kind="infoById.get(item.fileId)?.kind ?? 'pdf'" :label="label(item.fileId, item.page)" />
      </li>
    </ol>
  </section>
</template>
