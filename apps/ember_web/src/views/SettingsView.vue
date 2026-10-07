<script setup lang="ts">
import { computed, onMounted, ref, useTemplateRef } from "vue";
import SettingRow from "../components/SettingRow.vue";
import SettingsPanel from "../components/admin/SettingsPanel.vue";
import SegmentedControl from "../components/SegmentedControl.vue";
import ToggleSwitch from "../components/ToggleSwitch.vue";
import { DEFAULT_THEME, useTheme, type Theme } from "../composables/useTheme";
import { useAuthStore } from "../stores/auth";
import { useChatStore } from "../stores/chat";
import { filterSettings, type SearchableSetting } from "../utils/settingsSearch";

/** Every setting in one place, grouped by what it is for. A search box filters
 * them, and a setting that differs from its default shows a dot and a reset
 * button; the header counts how many are changed. The chat gear menu keeps its
 * quick switches; this page is the full list. */

interface SettingDef extends SearchableSetting {
  id: string;
  group: "chat" | "appearance" | "admin";
}

const GROUPS = [
  { id: "chat", title: "Chat" },
  { id: "appearance", title: "Appearance" },
  { id: "admin", title: "Administration" },
] as const;

const DEFS: SettingDef[] = [
  {
    id: "chat-terse",
    group: "chat",
    label: "Terse replies",
    description: "Ask the agent for short, terse answers.",
    keywords: ["caveman", "brief", "short"],
  },
  {
    id: "chat-ask-tools",
    group: "chat",
    label: "Ask before tools",
    description: "Ask you before the agent runs each tool.",
    keywords: ["approval", "allow", "permission"],
  },
  {
    id: "chat-chime",
    group: "chat",
    label: "Chime when done",
    description: "Play a short chime when an answer arrives while this tab is in the background.",
    keywords: ["sound", "notification", "audio"],
  },
  {
    id: "appearance-theme",
    group: "appearance",
    label: "Theme",
    description: "Light, dark, or follow your system.",
    keywords: ["dark mode", "light mode", "color"],
  },
  {
    id: "admin-tool-approval",
    group: "admin",
    label: "Tool approval",
    description: "Require approval for every tool, for every account.",
    keywords: ["force", "lock", "require", "administrator", "approval"],
  },
];

const THEME_OPTIONS: { value: Theme; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

const auth = useAuthStore();
const chat = useChatStore();
const { theme, setTheme } = useTheme();

const isAdmin = computed(() => auth.hasPermission("admin.manage"));
const query = ref("");
const root = useTemplateRef<HTMLElement>("root");

const available = computed(() => DEFS.filter((d) => d.group !== "admin" || isAdmin.value));
const shown = computed(() => new Set(filterSettings(available.value, query.value).map((d) => d.id)));
const groups = computed(() =>
  GROUPS.map((g) => ({ ...g, defs: available.value.filter((d) => d.group === g.id && shown.value.has(d.id)) })).filter(
    (g) => g.defs.length > 0,
  ),
);
const noMatches = computed(() => shown.value.size === 0);

// The tool approval switch keeps its own value (it is saved on the server); it
// tells this page when it differs from the default.
const toolApprovalModified = ref(false);

const themeModel = computed<Theme>({ get: () => theme.value, set: (value) => setTheme(value) });

const modified = computed(() => ({
  "chat-terse": chat.caveman !== false,
  "chat-ask-tools": chat.askBeforeTools !== false,
  "chat-chime": chat.chime !== true,
  "appearance-theme": theme.value !== DEFAULT_THEME,
  "admin-tool-approval": isAdmin.value && toolApprovalModified.value,
}));
const modifiedCount = computed(() => Object.values(modified.value).filter(Boolean).length);

function checked(event: Event): boolean {
  return (event.target as HTMLInputElement).checked;
}

/** Enter in the search box moves to the first setting that is left. */
function jumpToFirst(): void {
  const control = root.value?.querySelector<HTMLElement>(
    '[data-setting-id]:not([hidden]) input:not([disabled]), [data-setting-id]:not([hidden]) button:not(.reset)',
  );
  control?.focus();
}

onMounted(() => {
  // Whether an administrator forces tool approval decides if "Ask before tools" can change.
  void chat.refreshSettings();
});
</script>

<template>
  <section class="settings-view">
    <div ref="root" class="column">
      <header class="head">
        <h2>Settings</h2>
        <span v-if="modifiedCount > 0" class="badge" role="status">{{ modifiedCount }} modified</span>
      </header>

      <input
        v-model="query"
        class="search"
        type="search"
        placeholder="Search settings"
        aria-label="Search settings"
        autocomplete="off"
        @keydown.enter.prevent="jumpToFirst"
        @keydown.esc="query = ''"
      />

      <p v-if="noMatches" class="muted empty">
        No settings match "{{ query }}".
        <button type="button" class="link" @click="query = ''">Clear search</button>
      </p>

      <section v-for="g in groups" :key="g.id" class="group" :aria-label="g.title">
        <h3>{{ g.title }}</h3>

        <div v-if="g.id === 'chat'" class="card">
          <p class="note">Applies instantly. Saved on this device.</p>
          <SettingRow
            v-if="shown.has('chat-terse')"
            setting-id="chat-terse"
            label="Terse replies"
            description="Ask the agent for short, terse answers."
            :modified="modified['chat-terse']"
            @reset="chat.setCaveman(false)"
          >
            <ToggleSwitch small aria-label="Terse replies" :checked="chat.caveman" @change="chat.setCaveman(checked($event))" />
          </SettingRow>
          <SettingRow
            v-if="shown.has('chat-ask-tools')"
            setting-id="chat-ask-tools"
            label="Ask before tools"
            :description="
              chat.forceToolApproval
                ? 'Your administrator requires approval before every tool.'
                : 'Ask you before the agent runs each tool.'
            "
            :modified="modified['chat-ask-tools']"
            @reset="chat.setAskBeforeTools(false)"
          >
            <ToggleSwitch
              small
              aria-label="Ask before tools"
              :checked="chat.askBeforeTools || chat.forceToolApproval"
              :disabled="chat.forceToolApproval"
              @change="chat.setAskBeforeTools(checked($event))"
            />
          </SettingRow>
          <SettingRow
            v-if="shown.has('chat-chime')"
            setting-id="chat-chime"
            label="Chime when done"
            description="Play a short chime when an answer arrives while this tab is in the background."
            :modified="modified['chat-chime']"
            @reset="chat.setChime(true)"
          >
            <ToggleSwitch small aria-label="Chime when done" :checked="chat.chime" @change="chat.setChime(checked($event))" />
          </SettingRow>
        </div>

        <div v-else-if="g.id === 'appearance'" class="card">
          <p class="note">Applies instantly. Saved on this device.</p>
          <SettingRow
            setting-id="appearance-theme"
            label="Theme"
            description="Light, dark, or follow your system."
            :modified="modified['appearance-theme']"
            @reset="setTheme(DEFAULT_THEME)"
          >
            <SegmentedControl v-model="themeModel" :options="THEME_OPTIONS" aria-label="Theme" />
          </SettingRow>
        </div>
      </section>

      <SettingsPanel v-if="isAdmin" v-show="shown.has('admin-tool-approval')" class="admin-card" @modified="toolApprovalModified = $event" />
    </div>
  </section>
</template>

<style scoped>
.settings-view {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.column {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 820px;
  margin: 0 auto;
  padding: 24px 16px;
}
.head {
  display: flex;
  align-items: center;
  gap: 12px;
}
h2 {
  margin: 0;
  font-size: 1.2em;
}
.badge {
  padding: 1px 10px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-full);
  font-size: 0.8em;
  color: var(--accent);
}
.search {
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
.search:focus {
  outline: none;
  border-color: var(--accent);
}
.group h3 {
  margin: 0 0 8px;
  font-size: 0.8em;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
}
/* The tool approval card is not inside its group (it stays mounted while a
   search hides it, so an unsaved draft survives); close the gap to its heading. */
.admin-card {
  margin-top: -16px;
}
.card {
  padding: 4px 16px 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.note {
  margin: 8px 0 0;
  font-size: 0.8em;
  color: var(--muted);
}
.muted {
  color: var(--muted);
}
.empty {
  margin: 0;
}
.link {
  padding: 0;
  border: none;
  cursor: pointer;
  color: var(--accent);
  background: none;
  font: inherit;
  text-decoration: underline;
}
</style>
