<script setup lang="ts">
// One page preview. PDFs render to a canvas through pdf.js, images use <img>.
// Nothing loads until the thumbnail is near the viewport.
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { contentUrl } from '../api/client'
import type { FileKind } from '../api/types'
import { renderPage } from '../lib/pdfThumbs'
import type { PageItem } from '../lib/segments'

const props = defineProps<{ item: PageItem; kind: FileKind; label: string }>()
const THUMB_WIDTH = 96
const root = ref<HTMLElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const visible = ref(false)
const failed = ref(false)
let observer: IntersectionObserver | null = null

async function show(): Promise<void> {
  visible.value = true
  if (props.kind !== 'pdf' || !canvas.value) return
  try {
    await renderPage(contentUrl(props.item.fileId), props.item.page, canvas.value, THUMB_WIDTH)
  } catch {
    failed.value = true
  }
}

onMounted(() => {
  if (!root.value) return
  if (typeof IntersectionObserver === 'undefined') {
    void show()
    return
  }
  observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        observer?.disconnect()
        void show()
      }
    },
    { rootMargin: '200px' },
  )
  observer.observe(root.value)
})

onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <figure ref="root" class="thumb">
    <div class="paper" :style="{ transform: `rotate(${item.rotate}deg)` }">
      <canvas v-if="kind === 'pdf' && !failed" ref="canvas" />
      <img v-else-if="kind === 'image' && visible" :src="contentUrl(item.fileId)" alt="" draggable="false" />
      <span v-else-if="failed" class="muted small">No preview</span>
    </div>
    <figcaption class="small">{{ label }}</figcaption>
  </figure>
</template>
