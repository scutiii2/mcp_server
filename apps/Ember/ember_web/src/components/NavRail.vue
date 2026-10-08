<script setup lang="ts">
// The app's left rail: one icon per page the account may open (the name shows
// on hover or keyboard focus), then theme, account and log out. Visitors on
// the login pages get just the wordmark and the theme button. The account's own
// arrangement applies: pinned pages first, a divider, the rest, hidden ones left out.
import { computed } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import EmberLogo from "./EmberLogo.vue";
import { useTheme } from "../composables/useTheme";
import { CONFIG_ISSUES_ICON, OVERVIEW_ICON, PROFILE_ICON, visiblePages } from "../router/pages";
import { useAuthStore } from "../stores/auth";
import { useConfigIssuesStore } from "../stores/configIssues";
import { useNavPrefsStore } from "../stores/navPrefs";
import { ADMIN_ACCESS_PERMISSIONS, emberAdminUrl } from "../utils/adminLink";
import { railPages } from "../utils/navArrangement";

const { theme, next, cycle } = useTheme();
const THEME_LABELS = { system: "System", light: "Light", dark: "Dark" } as const;

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const adminUrl = emberAdminUrl();
const canAdmin = computed(() => ADMIN_ACCESS_PERMISSIONS.some(auth.hasPermission));
const canBrowse = computed(() => auth.account !== null && !auth.needsVerification);
const navPrefs = useNavPrefsStore();
// Nothing is drawn until the arrangement has loaded, so the icons don't jump.
const pages = computed(() =>
  canBrowse.value && navPrefs.ready
    ? railPages(visiblePages((p) => auth.hasPermission(p)), navPrefs.prefs)
    : { pinned: [], rest: [] },
);
const hasPages = computed(() => pages.value.pinned.length + pages.value.rest.length > 0);

// Narrow screens show a fixed bar instead: Overview, Capabilities, Chat in the
// middle, Usage, Profile. Only the permissions gate it; the arrangement does not.
interface Tab {
  to: string;
  label: string;
  icon: string[];
  /** Draw the Ember logo instead of the icon. */
  logo?: boolean;
  /** Beside the Chat button: its highlight runs under it. */
  near?: "l" | "r";
}
const tabs = computed(() => {
  const open = new Map(visiblePages((p) => auth.hasPermission(p)).map((p) => [p.to, p]));
  // A copy, so setting `near` below never touches the shared page list.
  const page = (to: string): Tab | undefined => {
    const p = open.get(to);
    return p && { to: p.to, label: p.label, icon: p.icon };
  };
  const left: Tab[] = [{ to: "/overview", label: "Overview", icon: OVERVIEW_ICON, logo: true }];
  const right: Tab[] = [{ to: "/account", label: "Profile", icon: PROFILE_ICON }];
  const capabilities = page("/capabilities");
  const usage = page("/usage");
  if (capabilities) left.push(capabilities);
  if (usage) right.unshift(usage);
  left[left.length - 1]!.near = "l";
  right[0]!.near = "r";
  return { left, right, chat: page("/") };
});

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

// A chat opened by id and a capability's own page have no rail item of
// their own, so they keep their parent page marked.
function isOpenedFromHere(to: string): boolean {
  return (
    (to === "/" && route.name === "chat-id") ||
    (to === "/capabilities" && route.name === "capability-page")
  );
}

async function logout(): Promise<void> {
  await auth.logout();
  await router.replace({ name: "login" });
}
</script>

<template>
  <aside class="rail">
    <RouterLink v-if="canBrowse" to="/overview" class="wordmark" data-label="Overview" aria-label="Ember - overview of every page"><EmberLogo /></RouterLink>
    <span v-else class="wordmark" role="img" aria-label="Ember"><EmberLogo /></span>

    <nav v-if="canBrowse" class="tabs" aria-label="Main pages">
      <template v-for="(side, i) in [tabs.left, tabs.right]" :key="i">
        <span v-if="i === 1" class="gap" aria-hidden="true" />
        <RouterLink
          v-for="t in side"
          :key="t.to"
          :to="t.to"
          :aria-label="t.label"
          :class="[t.near && `near-${t.near}`, { current: isOpenedFromHere(t.to) }]"
        >
          <EmberLogo v-if="t.logo" class="tab-logo" />
          <svg v-else viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
            <path v-for="d in t.icon" :key="d" :d="d" />
          </svg>
        </RouterLink>
      </template>
      <RouterLink
        v-if="tabs.chat"
        :to="tabs.chat.to"
        class="chat"
        :class="{ current: isOpenedFromHere(tabs.chat.to) }"
        aria-label="Chat"
      >
        <svg viewBox="0 0 24 24" width="38" height="38" aria-hidden="true">
          <path v-for="d in tabs.chat.icon" :key="d" :d="d" />
        </svg>
      </RouterLink>
    </nav>

    <nav v-if="hasPages" class="pages" aria-label="Pages">
      <template v-for="(group, i) in [pages.pinned, pages.rest]" :key="i">
        <span v-if="i === 1 && pages.pinned.length && pages.rest.length" class="divider" aria-hidden="true" />
        <RouterLink
          v-for="p in group"
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
      </template>
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
      <a v-if="canAdmin" :href="adminUrl" class="admin-link" data-label="Ember Admin" aria-label="Open Ember Admin">
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M12 3 3 7v5c0 5 5 8 9 10 4-2 9-5 9-10V7zM8 12l3 3 5-6" /></svg>
      </a>
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
/* Between the pinned pages and the rest. */
.divider {
  width: 20px;
  height: 1px;
  margin: 2px 0;
  background: var(--border);
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
  width: 36px;
  height: 36px;
  text-decoration: none;
}
.wordmark svg {
  width: 100%;
  height: 100%;
}

/* One shape for every control in the rail. */
nav a,
.alert,
.theme,
.admin-link,
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
.admin-link:hover,
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

/* The narrow-screen bar only; the column above is for wide screens. */
.tabs {
  display: none;
}

/* Narrow screens: a bar along the bottom with five fixed tabs and a big Chat
   button in the middle that rises above it. The selected tab's highlight runs
   under the Chat button when it is one of the two beside it. */
@media (max-width: 767px) {
  .rail {
    flex-direction: row;
    width: 100%;
    height: var(--rail-height);
    padding: 0 6px;
    border-right: none;
    border-top: 1px solid var(--border);
  }
  .wordmark,
  .pages,
  .alert,
  .bottom {
    display: none;
  }
  .tabs {
    position: relative;
    display: flex;
    flex: 1;
    flex-direction: row;
    align-items: center;
    height: 100%;
    margin: 0;
    gap: 0;
  }
  .tabs .gap {
    flex: 0 0 92px;
  }
  .tabs a {
    position: relative;
    flex: 1;
    display: grid;
    place-items: center;
    width: auto;
    height: 44px;
    margin: 0 2px;
    color: var(--muted);
    text-decoration: none;
    transition: color 0.2s ease;
  }
  .tabs a svg {
    position: relative;
  }
  .tabs a .tab-logo {
    width: 28px;
    height: 28px;
  }
  .tabs a::before {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: var(--radius-md);
    background: var(--bg);
    box-shadow: inset 0 -2px 0 var(--accent);
    opacity: 0;
    transition: opacity 0.22s ease;
  }
  .tabs a.near-l::before {
    right: -46px;
    border-radius: var(--radius-md) 0 0 var(--radius-md);
  }
  .tabs a.near-r::before {
    left: -46px;
    border-radius: 0 var(--radius-md) var(--radius-md) 0;
  }
  .tabs a.router-link-exact-active,
  .tabs a.current {
    color: var(--text);
  }
  .tabs a.router-link-exact-active::before,
  .tabs a.current::before {
    opacity: 1;
  }
  .tabs a.chat {
    position: absolute;
    left: 50%;
    top: -34px;
    z-index: 2;
    width: 84px;
    height: 84px;
    margin: 0;
    transform: translateX(-50%);
    border: 1px solid var(--border);
    border-radius: var(--radius-full);
    color: var(--text);
    background: var(--bg);
    /* A ring in the bar's colour cuts the circle out of the bar. */
    box-shadow: 0 0 0 6px var(--surface);
    transition: box-shadow 0.25s ease;
  }
  .tabs a.chat::before {
    display: none;
  }
  .tabs a.chat.router-link-exact-active,
  .tabs a.chat.current {
    box-shadow: 0 0 0 6px var(--surface), inset 0 -4px 0 var(--accent);
  }
}
@media (max-width: 767px) and (prefers-reduced-motion: reduce) {
  .tabs a,
  .tabs a::before,
  .tabs a.chat {
    transition: none;
  }
}
</style>
