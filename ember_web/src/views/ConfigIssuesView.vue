<script setup lang="ts">
import { onMounted, ref } from "vue";
import { configIssuesClient, type ConfigIssue } from "../api/ConfigIssuesClient";
import "../components/infoPage.css";
import { errorMessage } from "../utils/errors";

/** Problems in ember_api's config and secret files (port of chat_app's
 * Config issues page). File and key names only, never secret values. */

const issues = ref<ConfigIssue[]>([]);
const loading = ref(true);
const error = ref("");

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    issues.value = await configIssuesClient.list();
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="info-page">
    <div class="column">
      <div class="head">
        <h2>Config issues</h2>
        <button type="button" class="chip" :disabled="loading" @click="load">Check again</button>
      </div>
      <p class="muted intro">
        Problems in <code>ember_api/configs</code> and <code>ember_api/secrets</code>. Secret files are re-read on
        every check; changes to <code>config_app.json</code> take effect once ember_api restarts.
      </p>

      <p v-if="loading" class="muted">checking ...</p>
      <p v-else-if="error" class="error">{{ error }}</p>
      <p v-else-if="issues.length === 0" class="ok">No problems found.</p>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>Key</th>
              <th>Problem</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(i, n) in issues" :key="n">
              <td><code>{{ i.file }}</code></td>
              <td><code>{{ i.key }}</code></td>
              <td>{{ i.message }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.ok {
  color: #2e9d5b;
}
</style>
