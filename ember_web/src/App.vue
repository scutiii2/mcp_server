<script setup lang="ts">
import { storeToRefs } from "pinia";
import { watch } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";
import { useAuthStore } from "./stores/auth";

const auth = useAuthStore();
const { account } = storeToRefs(auth);
const route = useRoute();
const router = useRouter();

// The session can end mid-page (expired, or logged out elsewhere): any 401
// clears the account, and this sends the user back to the login page.
watch(account, (now) => {
  if (!now && !route.meta.guestOnly) void router.replace({ name: "login" });
});

async function logout(): Promise<void> {
  await auth.logout();
  await router.replace({ name: "login" });
}
</script>

<template>
  <header class="topbar">
    <span class="wordmark">Ember</span>
    <nav v-if="account?.email_verified">
      <RouterLink v-if="auth.hasPermission('chat.use')" to="/">Chat</RouterLink>
      <RouterLink v-if="auth.hasPermission('tools.use')" to="/tools">Tools</RouterLink>
      <RouterLink v-if="auth.hasPermission('admin.manage')" to="/admin">Admin</RouterLink>
    </nav>
    <div v-if="account" class="user">
      <span class="username" :title="account.email">{{ account.username }}</span>
      <button type="button" class="logout" @click="logout">Log out</button>
    </div>
  </header>
  <main class="page">
    <!-- KeepAlive: switching to Tools and back keeps the chat (and a turn in
         flight) intact. Keyed by account so a different user never gets the
         previous user's cached pages. -->
    <RouterView v-slot="{ Component }">
      <KeepAlive :key="account?.id ?? 'guest'" include="ChatView,ToolsView">
        <component :is="Component" />
      </KeepAlive>
    </RouterView>
  </main>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  height: 48px;
  padding: 0 16px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
}
.wordmark {
  /* Pushes nav + user to the right, whether or not nav is shown. */
  margin-right: auto;
  font-weight: 700;
  letter-spacing: -0.01em;
}
nav {
  display: flex;
  gap: 4px;
}
.user {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: 16px;
  font-size: 0.9em;
}
.username {
  color: var(--muted);
}
.logout {
  padding: 3px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  cursor: pointer;
  background: transparent;
}
.logout:hover {
  border-color: var(--accent);
}
nav a {
  padding: 4px 12px;
  border-radius: 999px;
  color: var(--muted);
  text-decoration: none;
}
nav a:hover {
  color: var(--text);
}
nav a.router-link-exact-active {
  color: var(--text);
  background: var(--surface);
}
/* Fills what the top bar leaves; each view manages its own scrolling. */
.page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
</style>
