<script setup lang="ts">
import { computed } from "vue";
import OverviewTile from "../components/OverviewTile.vue";
import { visiblePages } from "../router/pages";
import { useAuthStore } from "../stores/auth";

/** Every page this account may open, as tiles (port of chat_app's Overview
 * start page). Reached from the Ember wordmark. */

// A person, for the Account tile (it is not in the nav rail).
const ACCOUNT_ICON = ["M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2", "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0z"];

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
        <OverviewTile v-for="p in pages" :key="p.to" :to="p.to" :label="p.label" :description="p.description" :icon="p.icon" />
        <OverviewTile to="/account" label="Account" description="Your email, password and devices." :icon="ACCOUNT_ICON" />
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
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 14px;
}
</style>
