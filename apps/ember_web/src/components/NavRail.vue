<script setup lang="ts">
// The app's left rail: one icon per page the account may open (the name shows
// on hover or keyboard focus), then theme, account and log out. Visitors on
// the login pages get just the wordmark and the theme button.
import { computed } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { useTheme } from "../composables/useTheme";
import { CONFIG_ISSUES_ICON, visiblePages } from "../router/pages";
import { useAuthStore } from "../stores/auth";
import { useConfigIssuesStore } from "../stores/configIssues";

const { theme, next, cycle } = useTheme();
const THEME_LABELS = { system: "System", light: "Light", dark: "Dark" } as const;

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const canBrowse = computed(() => auth.account !== null && !auth.needsVerification);
const pages = computed(() => (canBrowse.value ? visiblePages((p) => auth.hasPermission(p)) : []));

const configIssues = useConfigIssuesStore();
const showConfigAlert = computed(() => canBrowse.value && configIssues.issues.length > 0);
const alertLabel = computed(() => {
  const parts = [
    [configIssues.errorCount, "error"],
    [configIssues.warningCount, "warning"],
  ]
    .filter(([n]) => n)
    .map(([n, word]) => `${n} ${word}${n === 1 ? "" : "s"}`);
  return `Config issues: ${parts.join(", ")}`;
});

// A chat opened by id, a capability's own page and an extension's own page
// have no rail item of their own, so they keep their parent page marked.
function isOpenedFromHere(to: string): boolean {
  return (
    (to === "/" && route.name === "chat-id") ||
    (to === "/capabilities" && route.name === "capability-page") ||
    (to === "/extensions" && route.name === "extension-page")
  );
}

async function logout(): Promise<void> {
  await auth.logout();
  await router.replace({ name: "login" });
}
</script>

<template>
  <aside class="rail">
    <RouterLink v-if="canBrowse" to="/overview" class="wordmark" data-label="Overview" aria-label="Ember - overview of every page">E</RouterLink>
    <span v-else class="wordmark" aria-label="Ember">E</span>

    <nav v-if="pages.length" aria-label="Pages">
      <RouterLink
        v-for="p in pages"
        :key="p.to"
        :to="p.to"
        :data-label="p.label"
        :aria-label="p.label"
        :class="{ current: isOpenedFromHere(p.to) }"
      >
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <path v-for="d in p.icon" :key="d" :d="d" />
        </svg>
      </RouterLink>
    </nav>

    <RouterLink
      v-if="showConfigAlert"
      to="/config-issues"
      class="alert"
      :class="configIssues.errorCount > 0 ? 'has-errors' : 'has-warnings'"
      :data-label="alertLabel"
      :aria-label="alertLabel"
    >
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <path v-for="d in CONFIG_ISSUES_ICON" :key="d" :d="d" />
      </svg>
      <span class="count">{{ configIssues.issues.length }}</span>
    </RouterLink>

    <div class="bottom">
      <button
        type="button"
        class="theme"
        :data-label="`Theme: ${THEME_LABELS[theme]}`"
        :aria-label="`Theme: ${THEME_LABELS[theme]}. Switch to ${THEME_LABELS[next()]}`"
        @click="cycle"
      >
        <svg v-if="theme === 'light'" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6L7 7M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4" />
        </svg>
        <svg v-else-if="theme === 'dark'" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" />
        </svg>
        <svg v-else viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <rect x="3" y="4" width="18" height="12" rx="2" />
          <path d="M8 20h8M12 16v4" />
        </svg>
      </button>
      <template v-if="auth.account">
        <RouterLink
          to="/account"
          class="account"
          :data-label="auth.account.username"
          :aria-label="`${auth.account.username} - account settings`"
        >
          {{ auth.account.username.charAt(0).toUpperCase() }}
        </RouterLink>
        <button type="button" class="logout" data-label="Log out" aria-label="Log out" @click="logout">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
          </svg>
        </button>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  width: 52px;
  flex-shrink: 0;
  padding: 10px 0;
  border-right: 1px solid var(--border);
  background: var(--surface);
  /* Above the page, so the hover labels can overlap it. */
  position: relative;
  z-index: 30;
}
nav {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
}
.bottom {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  margin-top: auto;
}
.wordmark {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  font-weight: 700;
  color: var(--bg);
  background: var(--accent);
  text-decoration: none;
}

/* One shape for every control in the rail. */
nav a,
.alert,
.theme,
.account,
.logout {
  position: relative;
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  padding: 0;
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--muted);
  background: transparent;
  text-decoration: none;
  font-size: 0.85em;
  font-weight: 600;
}
/* Config issues: red while any error exists, amber when only warnings. */
.alert {
  margin-top: 8px;
}
.alert {
  --tone: var(--warning);
}
.alert.has-errors {
  --tone: var(--status-failed);
}
.alert {
  color: var(--tone);
}
.alert .count {
  position: absolute;
  top: -2px;
  right: -2px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: var(--radius-full);
  font-size: 0.7rem;
  line-height: 16px;
  text-align: center;
  color: var(--bg);
  background: var(--tone);
}
nav a:hover,
.theme:hover,
.account:hover,
.logout:hover {
  color: var(--text);
  background: var(--bg);
}
nav a.router-link-exact-active,
nav a.current,
.account.router-link-exact-active {
  color: var(--text);
  background: var(--bg);
  box-shadow: inset 2px 0 0 var(--accent);
}
svg {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

/* The page name, beside the icon, on hover or keyboard focus. */
[data-label]:hover::after,
[data-label]:focus-visible::after {
  content: attr(data-label);
  position: absolute;
  left: calc(100% + 8px);
  top: 50%;
  transform: translateY(-50%);
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  white-space: nowrap;
  font-size: 0.85rem;
  font-weight: 400;
  color: var(--text);
  background: var(--surface);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
  pointer-events: none;
}

/* Narrow screens: a bar along the bottom instead of a column. */
@media (max-width: 767px) {
  .rail {
    flex-direction: row;
    width: 100%;
    height: 52px;
    padding: 0 8px;
    border-right: none;
    border-top: 1px solid var(--border);
  }
  nav {
    flex-direction: row;
    margin: 0;
    min-width: 0;
    overflow-x: auto;
    scrollbar-width: none;
  }
  .bottom {
    flex-direction: row;
    margin: 0 0 0 auto;
  }
  nav a.router-link-exact-active,
  nav a.current,
  .account.router-link-exact-active {
    box-shadow: inset 0 -2px 0 var(--accent);
  }
  [data-label]:hover::after,
  [data-label]:focus-visible::after {
    display: none;
  }
}
</style>
