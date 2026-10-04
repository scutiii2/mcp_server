<script setup lang="ts">
import { computed } from "vue";
import { RouterLink } from "vue-router";
import { visiblePages } from "../router/pages";
import { useAuthStore } from "../stores/auth";

/** Every page this account may open, as tiles (port of chat_app's Overview
 * start page). Reached from the Ember wordmark. */

const auth = useAuthStore();
const pages = computed(() => visiblePages((p) => auth.hasPermission(p)));
</script>

<template>
  <section class="overview">
    <div class="column">
      <h2>Ember</h2>
      <p v-if="auth.account" class="muted">Logged in as {{ auth.account.username }}.</p>
      <p v-if="pages.length === 0" class="muted">Your role gives you no pages yet - ask an administrator.</p>
      <div class="tiles">
        <RouterLink v-for="p in pages" :key="p.to" :to="p.to" class="tile">
          <span class="icon" aria-hidden="true">{{ p.label[0] }}</span>
          <span class="name">{{ p.label }}</span>
          <span class="description">{{ p.description }}</span>
        </RouterLink>
        <RouterLink to="/account" class="tile">
          <span class="icon" aria-hidden="true">A</span>
          <span class="name">Account</span>
          <span class="description">Your email, password and devices.</span>
        </RouterLink>
      </div>
    </div>
  </section>
</template>

<style scoped>
.overview {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.column {
  max-width: 900px;
  margin: 0 auto;
  padding: 32px 16px;
}
h2 {
  margin: 0 0 4px;
  font-size: 1.5em;
}
.muted {
  margin: 0 0 20px;
  color: var(--muted);
}
.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}
.tile {
  display: grid;
  grid-template-columns: auto 1fr;
  grid-template-rows: auto 1fr;
  gap: 4px 12px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  color: var(--text);
  background: var(--surface);
  text-decoration: none;
}
.tile:hover {
  border-color: var(--accent);
}
.icon {
  grid-row: span 2;
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  font-weight: 700;
  color: var(--accent-contrast);
  background: var(--accent);
}
.name {
  font-weight: 600;
}
.description {
  font-size: 0.85em;
  color: var(--muted);
}
</style>
