<script setup lang="ts">
import { computed, watch } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";
import { ADMIN_SECTIONS } from "../router/pages";
import { useAuthStore } from "../stores/auth";
import "../components/admin/adminPages.css";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const sections = computed(() => ADMIN_SECTIONS.filter((s) => Array.isArray(s.permission) ? s.permission.some(auth.hasPermission) : auth.hasPermission(s.permission)));
const current = computed(() => ADMIN_SECTIONS.find((s) => s.to === route.path)?.label ?? "Overview");
// Editing a held role may remove access to the page currently open.
watch(sections, (now) => {
  if (!now.some((s) => s.to === route.path)) void router.replace(now.length ? '/admin' : '/');
});
</script>

<template>
  <section class="admin-workspace">
    <aside class="admin-sidebar" aria-label="Workspace administration">
      <div class="sidebar-brand">Ember Admin<span>People &amp; workspace</span></div>
      <p class="nav-label">Administration</p>
      <nav aria-label="Administration pages">
        <RouterLink v-for="section in sections" :key="section.to" :to="section.to" :aria-current="route.path === section.to ? 'page' : undefined">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in section.icon" :key="d" :d="d" /></svg>
          {{ section.label }}
        </RouterLink>
      </nav>
      <div v-if="auth.account" class="sidebar-profile">
        <span class="profile-avatar" aria-hidden="true">{{ auth.account.username.slice(0, 2).toUpperCase() }}</span>
        <div><strong>{{ auth.account.username }}</strong><span>{{ auth.account.roles.join(', ') || 'Workspace account' }}</span></div>
      </div>
    </aside>
    <div class="admin-content">
      <div class="admin-column">
        <nav class="admin-breadcrumb" aria-label="Breadcrumb"><RouterLink to="/admin">Administration</RouterLink><span aria-hidden="true">/</span><span aria-current="page">{{ current }}</span></nav>
        <RouterView />
      </div>
    </div>
  </section>
</template>

<style scoped>
.admin-workspace { display: flex; flex: 1; min-height: 0; min-width: 0; }
.admin-sidebar { width: 222px; flex-shrink: 0; display: flex; flex-direction: column; padding: 28px 16px 20px; border-right: 1px solid var(--border); }
.sidebar-brand { padding: 0 10px 24px; font-weight: 600; }
.sidebar-brand span { display: block; margin-top: 3px; font-size: 0.78em; font-weight: 400; color: var(--muted); }
.nav-label { margin: 0; padding: 8px 10px; color: var(--muted); font-size: 0.72em; text-transform: uppercase; letter-spacing: 0.09em; }
.admin-sidebar nav { display: flex; flex-direction: column; gap: 5px; }
.admin-sidebar nav a { display: flex; align-items: center; gap: 10px; padding: 10px; border-radius: var(--radius-md); color: var(--muted); text-decoration: none; font-size: 0.9em; }
.admin-sidebar nav a:hover { background: var(--surface); color: var(--text); }
.admin-sidebar nav a[aria-current='page'] { color: var(--accent); background: color-mix(in srgb, var(--accent) 9%, var(--bg)); font-weight: 600; }
svg { width: 20px; height: 20px; flex-shrink: 0; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.sidebar-profile { display: flex; align-items: center; gap: 10px; margin-top: auto; padding: 16px 10px 0; border-top: 1px solid var(--border); font-size: 0.85em; }
.sidebar-profile > div { min-width: 0; overflow-wrap: anywhere; }
.sidebar-profile strong { font-weight: 500; }
.sidebar-profile div span { display: block; color: var(--muted); font-size: 0.85em; }
.profile-avatar { width: 34px; height: 34px; flex-shrink: 0; display: grid; place-items: center; border: 1px solid var(--border); border-radius: var(--radius-full); background: var(--surface); font-size: 0.8em; }
.admin-content { flex: 1; min-width: 0; min-height: 0; overflow-y: auto; }
.admin-column { max-width: 1060px; margin: 0 auto; padding: 30px 32px 48px; }
.admin-breadcrumb { display: flex; gap: 12px; margin-bottom: 20px; font-size: 0.8em; color: var(--muted); }
.admin-breadcrumb a { color: var(--muted); text-decoration: none; }
.admin-breadcrumb a:hover { color: var(--accent); }
.admin-breadcrumb [aria-current] { color: var(--text); }
@media (max-width: 1000px) { .admin-sidebar { width: 195px; } .admin-column { padding: 25px 22px; } }
@media (max-width: 767px) {
  .admin-workspace { flex-direction: column; }
  .admin-sidebar { width: 100%; padding: 7px 10px; border-right: none; border-bottom: 1px solid var(--border); }
  .sidebar-brand, .nav-label, .sidebar-profile { display: none; }
  .admin-sidebar nav { flex-direction: row; overflow-x: auto; }
  .admin-sidebar nav a { white-space: nowrap; padding: 9px; font-size: 0.78em; }
  .admin-sidebar nav svg { display: none; }
  .admin-column { padding: 22px 16px 30px; }
}
</style>
