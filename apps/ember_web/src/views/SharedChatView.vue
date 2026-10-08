<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute } from "vue-router";
import MarkdownContent from "../components/MarkdownContent.vue";
import { ApiError } from "../api/http";
import { sharesClient, type SharedChatView } from "../api/SharesClient";
import { errorMessage, formatUtc } from "../utils/errors";

/** A chat someone shared by link: a read-only copy of its questions and
 * answers. Open to anyone (no login); everything shown comes from
 * GET /api/shared/{token}, which already left out what must stay private. */

const route = useRoute();
const token = computed(() => String(route.params.token ?? ""));

const shared = ref<SharedChatView | null>(null);
const loading = ref(true);
// "gone": unknown, revoked or expired - the server does not say which.
const problem = ref<"gone" | "busy" | "error" | null>(null);
const problemText = ref("");

const originalTitle = document.title;

async function load(): Promise<void> {
  loading.value = true;
  problem.value = null;
  shared.value = null;
  const requested = token.value;
  try {
    const view = await sharesClient.read(requested);
    if (requested !== token.value) return;
    shared.value = view;
    document.title = `${view.title} - Ember`;
  } catch (err) {
    if (requested !== token.value) return;
    if (err instanceof ApiError && err.status === 404) problem.value = "gone";
    else if (err instanceof ApiError && err.status === 429) problem.value = "busy";
    else {
      problem.value = "error";
      problemText.value = errorMessage(err);
    }
  } finally {
    if (requested === token.value) loading.value = false;
  }
}

watch(token, load, { immediate: true });

onBeforeUnmount(() => {
  document.title = originalTitle;
});
</script>

<template>
  <section class="shared">
    <div class="column page-column">
      <p v-if="loading" class="status">Loading …</p>

      <div v-else-if="problem === 'gone'" class="status" role="alert">
        <h2 class="page-title">This link doesn't work</h2>
        <p>It never existed, or it was turned off, or it has expired. Ask whoever sent it for a new one.</p>
      </div>
      <div v-else-if="problem === 'busy'" class="status" role="alert">
        <h2 class="page-title">Too many requests</h2>
        <p>Wait a minute and reload this page.</p>
        <button type="button" @click="load">Try again</button>
      </div>
      <div v-else-if="problem === 'error'" class="status" role="alert">
        <h2 class="page-title">Couldn't load this chat</h2>
        <p>{{ problemText }}</p>
        <button type="button" @click="load">Try again</button>
      </div>

      <template v-else-if="shared">
        <header>
          <h2 class="page-title">{{ shared.title }}</h2>
          <p class="note page-description">
            A read-only copy, shared {{ formatUtc(shared.created_at) }}.
            <template v-if="shared.expires_at">This link stops working {{ formatUtc(shared.expires_at) }}.</template>
            Tool output and attached files are not included.
          </p>
        </header>

        <template v-for="(m, i) in shared.messages" :key="i">
          <!-- Only model output is rendered as markdown; the questions stay literal. -->
          <div v-if="m.role === 'user'" class="user-bubble">{{ m.content }}</div>
          <MarkdownContent v-else class="assistant" :text="m.content" />
        </template>
      </template>
    </div>
  </section>
</template>

<style scoped>
.shared {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.column {



  display: flex;
  flex-direction: column;
  gap: 18px;
}
header h2 {

  overflow-wrap: anywhere;
}
.note:not(.page-description) {
  margin: 0;
  font-size: 0.85em;
  color: var(--muted);
}
.status {
  margin-top: 15vh;
  text-align: center;
  color: var(--muted);
}
.status h2 {
  color: var(--text);
}
.status button {
  padding: 5px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  cursor: pointer;
  color: var(--text);
  background: transparent;
}
.user-bubble {
  align-self: flex-end;
  max-width: 80%;
  padding: 10px 14px;
  border-radius: var(--radius-xl) var(--radius-xl) var(--radius-sm) var(--radius-xl);
  background: var(--user-bubble);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.assistant {
  overflow-wrap: anywhere;
}
</style>
