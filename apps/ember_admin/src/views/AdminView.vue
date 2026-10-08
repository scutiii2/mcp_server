<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { adminClient, type AdminSummary } from "../api/AdminClient";
import AccountsPanel from "../components/admin/AccountsPanel.vue";
import InvitesPanel from "../components/admin/InvitesPanel.vue";
import RolesPanel from "../components/admin/RolesPanel.vue";
import SettingsPanel from "../components/admin/SettingsPanel.vue";
import StatTile from "../components/admin/StatTile.vue";
import SegmentedControl from "../components/SegmentedControl.vue";
import { useAuthStore } from "../stores/auth";
import { errorMessage } from "../utils/errors";

const TABS = [
  { id: "accounts", label: "Accounts", permissions: ["accounts.view", "accounts.manage", "accounts.delete", "roles.assign"] },
  { id: "roles", label: "Roles", permissions: ["roles.view", "roles.manage", "roles.assign"] },
  { id: "invites", label: "Invites", permissions: ["invites.manage"] },
  { id: "settings", label: "Settings", permissions: ["settings.manage"] },
] as const;
type TabId = (typeof TABS)[number]["id"];
const auth = useAuthStore();
const visibleTabs = computed(() => TABS.filter((t) => t.permissions.some(auth.hasPermission)));
const TAB_OPTIONS = computed(() => visibleTabs.value.map((t) => ({ value: t.id, label: t.label })));

const route = useRoute();
const router = useRouter();

// The tab lives in the URL (?tab=roles), so reload and back/forward keep it.
const tab = computed<TabId | undefined>(() => visibleTabs.value.find((t) => t.id === route.query.tab)?.id ?? visibleTabs.value[0]?.id);

const summary = ref<AdminSummary | null>(null);
const summaryError = ref("");

async function loadSummary(): Promise<void> {
  try {
    summary.value = await adminClient.summary();
    summaryError.value = "";
  } catch (err) {
    summaryError.value = errorMessage(err);
  }
}

onMounted(loadSummary);
// Counts change through the tabs (disable an account, revoke an invite), so
// they are read again whenever the tab changes.
watch(tab, loadSummary);

function select(id: string): void {
  void router.replace({ query: { ...route.query, tab: id } });
}
</script>

<template>
  <section class="admin-view">
    <div class="column">
      <header class="page-head">
        <div>
          <p class="eyebrow">Workspace administration</p>
          <h2>Admin</h2>
          <p class="description">Manage people, access, and workspace settings.</p>
        </div>
        <button v-if="auth.hasPermission('invites.manage')" type="button" class="invite-button" @click="select('invites')">＋ Invite account</button>
      </header>
      <div class="stats">
        <StatTile v-if="auth.hasPermission('accounts.view')" label="Accounts" :value="summary?.accounts ?? null"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0M20 21v-2a4 4 0 0 0-3-3.9M17 3a4 4 0 0 1 0 8" /></svg></StatTile>
        <StatTile v-if="auth.hasPermission('accounts.view')" label="Unverified" :value="summary?.unverified ?? null" warn><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 5h18v14H3zM3 5l9 7 9-7" /></svg></StatTile>
        <StatTile v-if="auth.hasPermission('accounts.view')" label="Disabled" :value="summary?.disabled ?? null"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 10h14v11H5zM8 10V7a4 4 0 0 1 8 0v3" /></svg></StatTile>
        <StatTile v-if="auth.hasPermission('invites.manage')" label="Open invites" :value="summary?.open_invites ?? null"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M22 2L9 15M22 2l-7 20-6-7-7-6z" /></svg></StatTile>
      </div>
      <p v-if="summaryError" class="error">Couldn't load the overview: {{ summaryError }}</p>
      <SegmentedControl v-if="tab" class="tabs" :model-value="tab" :options="TAB_OPTIONS" label="Section" aria-label="Admin section" @update:model-value="select" />

      <!-- v-if, not v-show: each panel reloads its data when opened, so a
           role created on one tab shows up in the Accounts dropdown. -->
      <AccountsPanel v-if="tab === 'accounts'" @changed="loadSummary" />
      <RolesPanel v-else-if="tab === 'roles'" />
      <InvitesPanel v-else-if="tab === 'invites'" @changed="loadSummary" />
      <div v-else-if="tab === 'settings'" class="admin-panel">
        <header class="section-head"><div><h3>Workspace settings</h3><p>Controls that apply to every account.</p></div></header>
        <SettingsPanel />
      </div>
    </div>
  </section>
</template>

<style scoped>
.admin-view {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.column {
  max-width: 980px;
  margin: 0 auto;
  padding: 30px 24px;
}
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 24px;
}
.page-head > div {
  min-width: 0;
}
.eyebrow {
  margin: 0 0 5px;
  color: var(--accent);
  font-size: 0.75em;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.description {
  margin: 0;
  color: var(--muted);
  font-size: 0.9em;
}
.invite-button {
  flex-shrink: 0;
  padding: 8px 16px;
  border: none;
  border-radius: var(--radius-full);
  cursor: pointer;
  color: var(--accent-contrast);
  background: var(--accent);
  font-weight: 600;
  white-space: nowrap;
}
.invite-button:hover {
  background: color-mix(in srgb, var(--accent) 90%, var(--text));
}
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.stats svg {
  width: 18px;
  height: 18px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
h2 {
  margin: 0 0 4px;
  font-size: 1.2em;
}
.stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 24px;
}
.error {
  margin: 0 0 12px;
  color: var(--danger);
}
.tabs {
  display: flex;
  width: 100%;
  padding-bottom: 10px;
  margin-bottom: 22px;
  border-bottom: 1px solid var(--border);
}
@media (max-width: 767px) {
  .column {
    padding: 22px 16px;
  }
  .page-head {
    align-items: flex-start;
  }
  .invite-button {
    padding: 7px 12px;
    font-size: 0.8em;
  }
  .stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    margin-bottom: 18px;
  }
}
</style>
