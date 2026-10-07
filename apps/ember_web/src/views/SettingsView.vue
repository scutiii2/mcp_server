<script setup lang="ts">
import { computed, onMounted, ref, useTemplateRef, watch } from "vue";
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

// Icon paths are on a 16px grid, stroke only. The scope chip says where a group's
// settings live; Administration has none, its card carries its own scope chip.
const SCOPE_NOTE = "Applies instantly. Saved on this device.";
const GROUPS = [
  { id: "chat", title: "Chat", icon: "M2 3h12v8H7l-3 3v-3H2z", scope: "This device" },
  {
    id: "appearance",
    title: "Appearance",
    icon: "M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.4 1.4M11.6 11.6L13 13M3 13l1.4-1.4M11.6 4.4L13 3",
    scope: "This device",
  },
  { id: "admin", title: "Administration", icon: "M8 1.5l5 2v4c0 3-2 5.5-5 7-3-1.5-5-4-5-7v-4z", scope: "" },
] as const;
const SEARCH_ICON = "M7 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10M11 11l3.5 3.5";

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
const onlyModified = ref(false);
const root = useTemplateRef<HTMLElement>("root");

const available = computed(() => DEFS.filter((d) => d.group !== "admin" || isAdmin.value));
const shown = computed(
  () =>
    new Set(
      filterSettings(available.value, query.value)
        .filter((d) => !onlyModified.value || modified.value[d.id as keyof typeof modified.value])
        .map((d) => d.id),
    ),
);
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

// With nothing left to show, the filter would only hide the whole page.
watch(modifiedCount, (count) => {
  if (count === 0) onlyModified.value = false;
});

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
      </header>

      <div class="top">
        <label class="search-box">
          <svg class="search-icon" viewBox="0 0 16 16" aria-hidden="true"><path :d="SEARCH_ICON" /></svg>
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
        </label>
        <button
          v-if="modifiedCount > 0"
          type="button"
          :class="['badge', { on: onlyModified }]"
          :aria-pressed="onlyModified"
          title="Show only the settings changed from their defaults"
          @click="onlyModified = !onlyModified"
        >
          {{ modifiedCount }} modified
        </button>
      </div>

      <p v-if="noMatches" class="muted empty">
        No settings match "{{ query }}".
        <button type="button" class="link" @click="query = ''">Clear search</button>
      </p>

      <section v-for="g in groups" :key="g.id" class="group" :aria-label="g.title">
        <div class="group-head">
          <span class="group-icon" aria-hidden="true">
            <svg viewBox="0 0 16 16"><path :d="g.icon" /></svg>
          </span>
          <h3>{{ g.title }}</h3>
          <span v-if="g.scope" class="scope" :title="SCOPE_NOTE">{{ g.scope }}</span>
        </div>

        <div v-if="g.id === 'chat'" class="card">
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
          <SettingRow
            v-if="shown.has('appearance-theme')"
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
.top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.search-box {
  position: relative;
  flex: 1 1 220px;
}
.search-icon,
.group-icon svg {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.search-icon {
  position: absolute;
  top: 50%;
  left: 12px;
  width: 16px;
  height: 16px;
  transform: translateY(-50%);
  color: var(--muted);
  pointer-events: none;
}
.search {
  box-sizing: border-box;
  width: 100%;
  padding: 8px 12px 8px 36px;
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
.badge {
  padding: 5px 12px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-full);
  cursor: pointer;
  font: inherit;
  font-size: 0.85em;
  white-space: nowrap;
  color: var(--accent);
  background: transparent;
}
.badge.on {
  color: var(--accent-contrast);
  background: var(--accent);
}
.group-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 8px;
}
.group-icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-md);
  color: var(--accent);
  background: var(--code-bg);
}
.group-icon svg {
  width: 16px;
  height: 16px;
}
.group-head h3 {
  margin: 0;
  font-size: 1em;
}
.scope {
  margin-left: auto;
  padding: 1px 8px;
  border-radius: var(--radius-full);
  font-size: 0.75em;
  color: var(--muted);
  background: var(--code-bg);
}
/* The tool approval card is not inside its group (it stays mounted while a
   search hides it, so an unsaved draft survives); close the gap to its heading. */
.admin-card {
  margin-top: -8px;
}
.card {
  padding: 4px 16px 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
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
