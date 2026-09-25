<script setup lang="ts">
import { RouterLink, RouterView } from "vue-router";
</script>

<template>
  <header class="topbar">
    <span class="wordmark">ember<span class="accent">_web</span></span>
    <nav>
      <RouterLink to="/">Chat</RouterLink>
      <RouterLink to="/tools">Tools</RouterLink>
    </nav>
  </header>
  <main class="page">
    <!-- KeepAlive: switching to Tools and back keeps the chat (and a turn in flight) intact. -->
    <RouterView v-slot="{ Component }">
      <KeepAlive>
        <component :is="Component" />
      </KeepAlive>
    </RouterView>
  </main>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 16px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
}
.wordmark {
  font-weight: 700;
  letter-spacing: -0.01em;
}
.accent {
  color: var(--accent);
}
nav {
  display: flex;
  gap: 4px;
}
nav a {
  padding: 4px 12px;
  border-radius: 999px;
  color: var(--muted);
  text-decoration: none;
}
nav a:hover {
  color: var(--text);
}
nav a.router-link-exact-active {
  color: var(--text);
  background: var(--surface);
}
/* Fills what the top bar leaves; each view manages its own scrolling. */
.page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
</style>
