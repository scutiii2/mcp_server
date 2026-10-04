<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed, watch } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";
import { useTheme } from "./composables/useTheme";
import { visiblePages } from "./router/pages";
import { useAuthStore } from "./stores/auth";

const { theme, next, cycle } = useTheme();
const THEME_LABELS = { system: "System", light: "Light", dark: "Dark" } as const;

const auth = useAuthStore();
const { account } = storeToRefs(auth);
const route = useRoute();
const router = useRouter();

// The session can end mid-page (expired, or logged out elsewhere): any 401
// clears the account, and this sends the user back to the login page.
watch(account, (now) => {
  if (!now && !route.meta.guestOnly && !route.meta.public) void router.replace({ name: "login" });
});

const pages = computed(() => visiblePages((p) => auth.hasPermission(p)));

async function logout(): Promise<void> {
  await auth.logout();
  await router.replace({ name: "login" });
}
</script>

<template>
  <header class="topbar">
    <RouterLink v-if="account && !auth.needsVerification" to="/overview" class="wordmark" title="Overview of every page">Ember</RouterLink>
    <span v-else class="wordmark">Ember</span>
    <nav v-if="account && !auth.needsVerification">
      <RouterLink v-for="p in pages" :key="p.to" :to="p.to" :class="{ current: p.to === '/' && route.name === 'chat-id' }">{{
        p.label
      }}</RouterLink>
    </nav>
    <button
      type="button"
      class="theme"
      :title="`Theme: ${THEME_LABELS[theme]} (click for ${THEME_LABELS[next()]})`"
      :aria-label="`Theme: ${THEME_LABELS[theme]}. Switch to ${THEME_LABELS[next()]}`"
      @click="cycle"
    >
      <svg v-if="theme === 'light'" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
        <circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="1.8" />
        <path
          d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6L7 7M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
        />
      </svg>
      <svg v-else-if="theme === 'dark'" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
        <path
          d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linejoin="round"
        />
      </svg>
      <svg v-else viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
        <rect x="3" y="4" width="18" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.8" />
        <path d="M8 20h8M12 16v4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
      </svg>
    </button>
    <div v-if="account" class="user">
      <RouterLink to="/account" class="username" :title="`${account.email} - account settings`">
        {{ account.username }}
      </RouterLink>
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
  color: var(--text);
  text-decoration: none;
}
nav {
  display: flex;
  gap: 4px;
  min-width: 0;
  /* Many pages on a narrow screen: scroll the tabs, not the page. */
  overflow-x: auto;
  scrollbar-width: none;
}
nav a {
  white-space: nowrap;
}
.theme {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  margin-left: 12px;
  padding: 0;
  border: none;
  border-radius: 50%;
  cursor: pointer;
  color: var(--muted);
  background: transparent;
}
.theme:hover {
  color: var(--text);
  background: var(--surface);
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
  text-decoration: none;
}
.username:hover,
.username.router-link-exact-active {
  color: var(--text);
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
nav a.router-link-exact-active,
nav a.current {
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
