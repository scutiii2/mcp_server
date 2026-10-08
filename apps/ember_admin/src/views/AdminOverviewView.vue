<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { adminClient, type AdminSummary } from "../api/AdminClient";
import { ADMIN_PAGES } from "../router/pages";
import { useAuthStore } from "../stores/auth";
import { errorMessage } from "../utils/errors";
import StatTile from "../components/admin/StatTile.vue";
import "../components/admin/admin.css";

const auth = useAuthStore();
const summary = ref<AdminSummary | null>(null);
const error = ref("");
const destinations = computed(() => ADMIN_PAGES.filter(s => s.to !== "/admin").filter((s) => Array.isArray(s.permission) ? s.permission.some(auth.hasPermission) : auth.hasPermission(s.permission)));
const descriptions: Record<string, string> = {
  "/admin/accounts": "Manage profiles, account status, and assigned roles.",
  "/admin/roles": "Define exactly what each role can view and change.",
  "/admin/invites": "Create an invite, check expiry, or revoke access.",
  "/capabilities": "Browse capabilities, manage availability, and test their tools.",
  "/extensions": "Manage shared extensions and explore their tools.",
  "/analytics": "Review logs, errors, chat activity, and traffic.",
  "/admin/settings": "Control approval requirements for every account.",
};
onMounted(async () => {
  if (!auth.hasPermission("accounts.view") && !auth.hasPermission("invites.manage")) return;
  try { summary.value = await adminClient.summary(); }
  catch (err) { error.value = errorMessage(err); }
});
</script>

<template>
  <div class="admin-overview admin-panel">
    <header class="admin-page-head"><div><h2 class="page-title">Workspace overview</h2><p class="page-description">Manage people, access, integrations, and activity.</p></div><RouterLink v-if="auth.hasPermission('invites.manage')" class="primary" to="/admin/invites?create=1">＋ Create invite</RouterLink></header>
    <p v-if="error" class="error" role="alert">Couldn't load the overview: {{ error }}</p>
    <div v-if="auth.hasPermission('accounts.view') || auth.hasPermission('invites.manage')" class="stats">
      <RouterLink v-if="auth.hasPermission('accounts.view')" to="/admin/accounts"><StatTile label="Accounts" :value="summary?.accounts ?? null" /><span class="stat-link">Browse accounts →</span></RouterLink>
      <RouterLink v-if="auth.hasPermission('accounts.view')" to="/admin/accounts?status=unverified"><StatTile label="Unverified" :value="summary?.unverified ?? null" warn /><span class="stat-link">Review accounts →</span></RouterLink>
      <RouterLink v-if="auth.hasPermission('accounts.view')" to="/admin/accounts?status=disabled"><StatTile label="Disabled" :value="summary?.disabled ?? null" /><span class="stat-link">Review accounts →</span></RouterLink>
      <RouterLink v-if="auth.hasPermission('invites.manage')" to="/admin/invites"><StatTile label="Open invites" :value="summary?.open_invites ?? null" /><span class="stat-link">Manage invites →</span></RouterLink>
    </div>
    <div v-if="auth.hasPermission('accounts.view') && summary?.unverified" class="admin-info">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 10 18H2zM12 9v5m0 3v1" /></svg>
      <div><h3>{{ summary.unverified }} {{ summary.unverified === 1 ? 'account hasn’t' : 'accounts haven’t' }} verified their email</h3><p>Review their details or resend a verification email.</p></div>
      <RouterLink class="small" to="/admin/accounts?status=unverified">Review accounts</RouterLink>
    </div>
    <h3 class="destinations-title">Manage your workspace</h3>
    <div class="destinations">
      <RouterLink v-for="section in destinations" :key="section.to" :to="section.to" class="destination">
        <span class="destination-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in section.icon" :key="d" :d="d" /></svg></span>
        <div><h3>{{ section.label }}</h3><p>{{ descriptions[section.to] }}</p></div><span class="arrow" aria-hidden="true">→</span>
      </RouterLink>
    </div>
  </div>
</template>

<style scoped>
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 25px; }
.stats > a { position: relative; color: var(--text); text-decoration: none; border-radius: var(--radius-lg); }
.stats :deep(.tile) { padding: 16px 18px 42px; background: var(--bg); }
.stat-link { position: absolute; bottom: 15px; left: 18px; color: var(--accent); font-size: 0.78em; }
.admin-overview h3.destinations-title { margin: 28px 0 13px; }
.destinations { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 13px; }
.destination { display: flex; align-items: flex-start; gap: 14px; padding: 19px; border: 1px solid var(--border); border-radius: var(--radius-lg); color: var(--text); text-decoration: none; }
.destination:hover { border-color: var(--accent); }
.destination-icon { display: flex; flex-shrink: 0; padding: 10px; border-radius: var(--radius-md); color: var(--accent); background: var(--surface); }
.destination svg { width: 20px; height: 20px; }
.destination h3 { margin: 0; font-size: 0.95em; }
.destination p { margin: 4px 0 0; color: var(--muted); font-size: 0.86em; }
.arrow { margin-left: auto; color: var(--muted); }
@media (max-width: 767px) { .destinations { grid-template-columns: minmax(0, 1fr); } .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } .destination { padding: 15px; } }
</style>
