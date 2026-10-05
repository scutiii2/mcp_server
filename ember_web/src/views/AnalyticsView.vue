<script setup lang="ts">
import "../components/infoPage.css";
import LogEntries from "../components/LogEntries.vue";

/** Analytics page (was Logs). Any `logs.*` permission opens it; the raw
 * entries stay available as a list. */
</script>

<template>
  <section class="info-page">
    <div class="column">
      <h2>Analytics</h2>
      <LogEntries />
    </div>
  </section>
</template>
