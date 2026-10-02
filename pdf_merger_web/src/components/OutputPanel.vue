<script setup lang="ts">
// Output file name, metadata and image defaults.
import { usePlanStore } from '../stores/plan'

const plan = usePlanStore()
</script>

<template>
  <section class="panel">
    <h2>Output</h2>
    <div class="grid">
      <label>File name<input v-model="plan.output.filename" placeholder="merged.pdf" /></label>
      <label>Title<input v-model="plan.output.title" placeholder="Contract package" /></label>
      <label>Author<input v-model="plan.output.author" placeholder="Jane Cruz" /></label>
      <label
        >Image page size
        <select v-model="plan.output.image_page_size">
          <option value="A4">A4</option>
          <option value="Letter">Letter</option>
          <option value="match">Match image</option>
        </select>
      </label>
      <label
        >Image fit
        <select v-model="plan.output.image_fit">
          <option value="fit">Fit page</option>
          <option value="fill">Fill page</option>
          <option value="original">Original size</option>
        </select>
      </label>
      <label
        >Image margin (mm)
        <input v-model.number="plan.output.image_margin_mm" type="number" min="0" max="50" step="1" />
      </label>
      <label class="check"><input v-model="plan.output.bookmarks" type="checkbox" /> Bookmark each source</label>
    </div>
  </section>
</template>
