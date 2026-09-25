<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import AccountsPanel from "../components/admin/AccountsPanel.vue";
import InvitesPanel from "../components/admin/InvitesPanel.vue";
import RolesPanel from "../components/admin/RolesPanel.vue";

const TABS = [
  { id: "accounts", label: "Accounts" },
  { id: "roles", label: "Roles" },
  { id: "invites", label: "Invites" },
] as const;
type TabId = (typeof TABS)[number]["id"];

const route = useRoute();
const router = useRouter();

// The tab lives in the URL (?tab=roles), so reload and back/forward keep it.
const tab = computed<TabId>(() => TABS.find((t) => t.id === route.query.tab)?.id ?? "accounts");

function select(id: TabId): void {
  void router.replace({ query: { ...route.query, tab: id } });
}
</script>

<template>
  <section class="admin-view">
    <div class="column">
      <h2>Admin</h2>
      <nav class="tabs" role="tablist">
        <button
          v-for="t in TABS"
          :key="t.id"
          type="button"
          role="tab"
          :aria-selected="tab === t.id"
          :class="{ active: tab === t.id }"
          @click="select(t.id)"
        >
          {{ t.label }}
        </button>
      </nav>

      <!-- v-if, not v-show: each panel reloads its data when opened, so a
           role created on one tab shows up in the Accounts dropdown. -->
      <AccountsPanel v-if="tab === 'accounts'" />
      <RolesPanel v-else-if="tab === 'roles'" />
      <InvitesPanel v-else />
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
.tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 18px;
  border-bottom: 1px solid var(--border);
}
.tabs button {
  padding: 8px 14px;
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  cursor: pointer;
  color: var(--muted);
  background: transparent;
  font: inherit;
}
.tabs button.active {
  color: var(--text);
  border-bottom-color: var(--accent);
  font-weight: 600;
}
</style>
