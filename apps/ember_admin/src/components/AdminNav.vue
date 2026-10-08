<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { ADMIN_PAGES } from "../router/pages";

const auth = useAuthStore();
const route = useRoute();

const pages = computed(() =>
  ADMIN_PAGES.filter((p) => (Array.isArray(p.permission) ? p.permission.some(auth.hasPermission) : auth.hasPermission(p.permission))),
);
</script>

<template>
  <nav class="nav" aria-label="Admin sections">
    <RouterLink to="/" class="brand">Ember Admin</RouterLink>
    <RouterLink v-for="page in pages" :key="page.to" :to="page.to" class="item" :aria-current="route.path === page.to ? 'page' : undefined">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in page.icon" :key="d" :d="d" /></svg>
      <span>{{ page.label }}</span>
    </RouterLink>
    <button v-if="auth.account" type="button" class="signout" @click="auth.logout()">Sign out</button>
  </nav>
</template>

<style scoped>
.nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 200px;
  padding: 16px 12px;
  border-right: 1px solid var(--border);
  background: var(--surface);
}
.brand {
  margin-bottom: 12px;
  font-weight: 700;
  color: var(--accent);
  text-decoration: none;
}
.item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  color: var(--text);
  text-decoration: none;
}
.item:hover {
  background: var(--bg);
}
.item[aria-current="page"] {
  color: var(--accent);
  background: var(--bg);
  font-weight: 600;
}
.item svg {
  width: 20px;
  height: 20px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.signout {
  margin-top: auto;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--muted);
  font: inherit;
  cursor: pointer;
}
:is(a, button):focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
@media (max-width: 767px) {
  .nav {
    flex-direction: row;
    width: auto;
    overflow-x: auto;
    padding: 8px 12px;
    border-right: none;
    border-bottom: 1px solid var(--border);
  }
  .brand,
  .signout {
    display: none;
  }
}
</style>
