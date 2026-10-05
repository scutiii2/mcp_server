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
import { errorMessage } from "../utils/errors";

const TABS = [
  { id: "accounts", label: "Accounts" },
  { id: "roles", label: "Roles" },
  { id: "invites", label: "Invites" },
  { id: "settings", label: "Settings" },
] as const;
type TabId = (typeof TABS)[number]["id"];
const TAB_OPTIONS = TABS.map((t) => ({ value: t.id, label: t.label }));

const route = useRoute();
const router = useRouter();

// The tab lives in the URL (?tab=roles), so reload and back/forward keep it.
const tab = computed<TabId>(() => TABS.find((t) => t.id === route.query.tab)?.id ?? "accounts");

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

function select(id: TabId): void {
  void router.replace({ query: { ...route.query, tab: id } });
}
</script>

<template>
  <section class="admin-view">
    <div class="column">
      <h2>Admin</h2>
      <div class="stats">
        <StatTile label="Accounts" :value="summary?.accounts ?? null" />
        <StatTile label="Unverified" :value="summary?.unverified ?? null" warn />
        <StatTile label="Disabled" :value="summary?.disabled ?? null" />
        <StatTile label="Open invites" :value="summary?.open_invites ?? null" />
      </div>
      <p v-if="summaryError" class="error">Couldn't load the overview: {{ summaryError }}</p>
      <SegmentedControl class="tabs" :model-value="tab" :options="TAB_OPTIONS" aria-label="Admin section" @update:model-value="select" />

      <!-- v-if, not v-show: each panel reloads its data when opened, so a
           role created on one tab shows up in the Accounts dropdown. -->
      <AccountsPanel v-if="tab === 'accounts'" @changed="loadSummary" />
      <RolesPanel v-else-if="tab === 'roles'" />
      <InvitesPanel v-else-if="tab === 'invites'" />
      <SettingsPanel v-else />
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
  max-width: 820px;
  margin: 0 auto;
  padding: 24px 16px;
}
h2 {
  margin: 0 0 12px;
  font-size: 1.2em;
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
  margin-bottom: 16px;
}
.error {
  margin: 0 0 12px;
  color: var(--danger);
}
.tabs {
  margin-bottom: 18px;
}
</style>
