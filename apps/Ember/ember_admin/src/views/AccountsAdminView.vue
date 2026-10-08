<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import type { AccountStatus } from "../api/AdminClient";
import AccountsPanel from "../components/admin/AccountsPanel.vue";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const filters = computed(() => ({
  q: typeof route.query.q === 'string' ? route.query.q : '',
  status: (route.query.status === 'unverified' || route.query.status === 'disabled' ? route.query.status : 'all') as AccountStatus,
}));
function updateFilters(next: { q: string; status: AccountStatus }): void {
  void router.replace({ query: { ...route.query, q: next.q || undefined, status: next.status === 'all' ? undefined : next.status } });
}
</script>
<template>
  <div class="admin-panel"><header class="admin-page-head"><div><h2 class="page-title">Accounts</h2><p class="page-description">Manage people and their workspace access.</p></div><RouterLink v-if="auth.hasPermission('invites.manage')" class="primary" to="/admin/invites?create=1">＋ Create invite</RouterLink></header><AccountsPanel :show-heading="false" :filters="filters" @filter="updateFilters" /></div>
</template>
