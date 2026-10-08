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
.admin-content { flex: 1; min-width: 0; min-height: 0; overflow-y: auto; }
.admin-column { max-width: 1060px; margin: 0 auto; padding: 30px 32px 48px; }
.admin-breadcrumb { display: flex; gap: 12px; margin-bottom: 20px; font-size: 0.8em; color: var(--muted); }
.admin-breadcrumb a { color: var(--muted); text-decoration: none; }
.admin-breadcrumb a:hover { color: var(--accent); }
.admin-breadcrumb [aria-current] { color: var(--text); }
@media (max-width: 1000px) { .admin-column { padding: 25px 22px; } }
@media (max-width: 767px) { .admin-column { padding: 22px 16px 30px; } }
</style>
