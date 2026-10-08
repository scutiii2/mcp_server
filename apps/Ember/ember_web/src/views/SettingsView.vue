<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, useTemplateRef, watch } from "vue";
import { getCurrentInstance } from "vue";
import { onBeforeRouteLeave, routerKey } from "vue-router";
import { navPreferencesClient } from "../api/NavPreferencesClient";
import ConfirmModal from "../components/ConfirmModal.vue";
import { errorMessage } from "../utils/errors";
import SettingRow from "../components/SettingRow.vue";
import SidebarEditor from "../components/SidebarEditor.vue";
import SegmentedControl from "../components/SegmentedControl.vue";
import ToggleSwitch from "../components/ToggleSwitch.vue";
import { DEFAULT_THEME, useTheme, type Theme } from "../composables/useTheme";
import { useAuthStore } from "../stores/auth";
import { useChatStore } from "../stores/chat";
import { useNavPrefsStore } from "../stores/navPrefs";
import { isDefault } from "../utils/navArrangement";
import { filterSettings, type SearchableSetting } from "../utils/settingsSearch";

/** Every setting in one place, grouped by what it is for. A search box filters
 * them, and a setting that differs from its default shows a dot and a reset
 * button; the header counts how many are changed. The chat gear menu keeps its
 * quick switches; this page is the full list. */

interface SettingDef extends SearchableSetting {
  id: string;
  group: "chat" | "appearance" | "sidebar";
}

// Icon paths are on a 16px grid, stroke only. The scope chip says where a group's
// settings live.
const SCOPE_NOTE = "Applied when you save. Stored on this device.";
const GROUPS = [
  { id: "chat", title: "Chat", icon: "M2 3h12v8H7l-3 3v-3H2z", scope: "This device" },
  {
    id: "appearance",
    title: "Appearance",
    icon: "M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.4 1.4M11.6 11.6L13 13M3 13l1.4-1.4M11.6 4.4L13 3",
    scope: "This device",
  },
  {
    id: "sidebar",
    title: "Sidebar",
    icon: "M2 2.5h12v11H2zM6 2.5v11",
    scope: "Your account",
    note: "Applied when you save. Stored on your account.",
  },
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
    id: "chat-suggestions",
    group: "chat",
    label: "Suggest next prompt",
    description: "Show a predicted next message in the chat box; press Tab to use it. Uses a small model call per answer. Saved to your account.",
    keywords: ["autocomplete", "tab", "placeholder", "prediction", "follow-up"],
  },
  {
    id: "appearance-theme",
    group: "appearance",
    label: "Theme",
    description: "Light, dark, or follow your system.",
    keywords: ["dark mode", "light mode", "color"],
  },
  {
    id: "sidebar-pages",
    group: "sidebar",
    label: "Pages",
    description: "Order, pin or hide the pages in the sidebar.",
    keywords: ["rearrange", "reorder", "navigation", "menu", "rail", "icons", "pin", "hide", "drag"],
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
const navPrefs = useNavPrefsStore();

const query = ref("");
const onlyModified = ref(false);
const root = useTemplateRef<HTMLElement>("root");

const available = computed(() => DEFS);
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

const saved = computed(() => ({
  caveman: chat.caveman, askBeforeTools: chat.askBeforeTools, chime: chat.chime,
  suggestions: auth.promptSuggestions, theme: theme.value,
  sidebar: { order: [...navPrefs.prefs.order], pinned: [...navPrefs.prefs.pinned], hidden: [...navPrefs.prefs.hidden] },
}));
const draft = ref(structuredClone(saved.value));
const saving = ref(false);
const saveError = ref("");
const dirty = computed(() => JSON.stringify(draft.value) !== JSON.stringify(saved.value));
watch(saved, (next, previous) => {
  if (saving.value) return;
  for (const key of Object.keys(next) as (keyof typeof next)[]) {
    if (JSON.stringify(draft.value[key]) === JSON.stringify(previous[key])) {
      Object.assign(draft.value, { [key]: structuredClone(next[key]) });
    }
  }
});
watch(() => auth.account?.id, () => { draft.value = structuredClone(saved.value); saveError.value = ""; });
function revert(): void { draft.value = structuredClone(saved.value); saveError.value = ""; }
async function save(): Promise<void> {
  if (saving.value || !dirty.value) return;
  saving.value = true;
  saveError.value = "";
  const accountId = auth.account?.id;
  const next: typeof saved.value = JSON.parse(JSON.stringify(draft.value));
  try {
    if (next.suggestions !== auth.promptSuggestions) await auth.setPromptSuggestions(next.suggestions);
    if (accountId !== auth.account?.id) return;
    if (JSON.stringify(next.sidebar) !== JSON.stringify(navPrefs.prefs)) {
      const result = await navPreferencesClient.save(next.sidebar);
      if (accountId !== auth.account?.id) return;
      navPrefs.prefs = result;
      draft.value.sidebar = structuredClone(result);
    }
    chat.setCaveman(next.caveman);
    if (!chat.forceToolApproval) chat.setAskBeforeTools(next.askBeforeTools);
    else draft.value.askBeforeTools = chat.askBeforeTools;
    chat.setChime(next.chime);
    setTheme(next.theme);
  } catch (err) { if (accountId === auth.account?.id) saveError.value = errorMessage(err); }
  finally { saving.value = false; }
}
const discardOpen = ref(false);
let discardAnswer: ((value: boolean) => void) | null = null;
function answerDiscard(discard: boolean): void {
  if (discard) revert();
  discardOpen.value = false;
  discardAnswer?.(discard);
  discardAnswer = null;
}
// Unit mounts without a router still exercise draft/save behavior.
if (getCurrentInstance()?.appContext.provides[routerKey as symbol]) onBeforeRouteLeave(() => {
  if (saving.value) return false;
  if (!dirty.value) return true;
  discardOpen.value = true;
  return new Promise<boolean>(resolve => { discardAnswer = resolve; });
});
function beforeUnload(event: BeforeUnloadEvent): void {
  if (dirty.value || saving.value) { event.preventDefault(); event.returnValue = ""; }
}
onMounted(() => window.addEventListener("beforeunload", beforeUnload));
onUnmounted(() => { window.removeEventListener("beforeunload", beforeUnload); answerDiscard(false); });

const modified = computed(() => ({
  "chat-terse": draft.value.caveman !== false,
  "chat-ask-tools": draft.value.askBeforeTools !== false,
  "chat-chime": draft.value.chime !== true,
  "chat-suggestions": !draft.value.suggestions,
  "appearance-theme": draft.value.theme !== DEFAULT_THEME,
  "sidebar-pages": !isDefault(draft.value.sidebar),
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
  <section class="settings-view" :class="{ dirty }">
    <div ref="root" class="column page-column">
      <header class="head">
        <div><h2 class="page-title">Settings</h2><p class="page-description">Adjust chat, appearance, and navigation preferences.</p></div>
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

      <section v-for="g in groups" :key="g.id" class="group" :aria-label="g.title"><fieldset :disabled="saving" class="settings-controls">
        <div class="group-head">
          <span class="group-icon" aria-hidden="true">
            <svg viewBox="0 0 16 16"><path :d="g.icon" /></svg>
          </span>
          <h3>{{ g.title }}</h3>
          <span v-if="g.scope" class="scope" :title="'note' in g ? g.note : SCOPE_NOTE">{{ g.scope }}</span>
        </div>

        <div v-if="g.id === 'chat'" class="card">
          <SettingRow
            v-if="shown.has('chat-terse')"
            setting-id="chat-terse"
            label="Terse replies"
            description="Ask the agent for short, terse answers."
            :modified="modified['chat-terse']"
            @reset="draft.caveman = false"
          >
            <ToggleSwitch small aria-label="Terse replies" :checked="draft.caveman" @change="draft.caveman = checked($event)" />
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
            @reset="draft.askBeforeTools = false"
          >
            <ToggleSwitch
              small
              aria-label="Ask before tools"
              :checked="draft.askBeforeTools || chat.forceToolApproval"
              :disabled="chat.forceToolApproval"
              @change="draft.askBeforeTools = checked($event)"
            />
          </SettingRow>
          <SettingRow
            v-if="shown.has('chat-chime')"
            setting-id="chat-chime"
            label="Chime when done"
            description="Play a short chime when an answer arrives while this tab is in the background."
            :modified="modified['chat-chime']"
            @reset="draft.chime = true"
          >
            <ToggleSwitch small aria-label="Chime when done" :checked="draft.chime" @change="draft.chime = checked($event)" />
          </SettingRow>
          <SettingRow
            v-if="shown.has('chat-suggestions')"
            setting-id="chat-suggestions"
            label="Suggest next prompt"
            description="Show a predicted next message in the chat box; press Tab to use it. Uses a small model call per answer. Saved to your account."
            :modified="modified['chat-suggestions']"
            @reset="draft.suggestions = true"
          >
            <ToggleSwitch
              small
              aria-label="Suggest next prompt"
              :checked="draft.suggestions"
              @change="draft.suggestions = checked($event)"
            />
          </SettingRow>
        </div>

        <div v-else-if="g.id === 'appearance'" class="card">
          <SettingRow
            v-if="shown.has('appearance-theme')"
            setting-id="appearance-theme"
            label="Theme"
            description="Light, dark, or follow your system."
            :modified="modified['appearance-theme']"
            @reset="draft.theme = DEFAULT_THEME"
          >
            <SegmentedControl v-model="draft.theme" :options="THEME_OPTIONS" aria-label="Theme" />
          </SettingRow>
        </div>

        <div v-else-if="g.id === 'sidebar'" class="card">
          <SidebarEditor v-if="shown.has('sidebar-pages')" v-model="draft.sidebar" />
        </div>
      </fieldset></section>

    </div>
    <div v-if="dirty || saving" class="settings-save-bar" role="group" aria-label="Unsaved settings" :aria-busy="saving">
      <div><span>Unsaved changes</span><p v-if="saveError" class="save-error" role="alert">{{ saveError }}</p></div>
      <button type="button" class="revert" :disabled="saving" @click="revert">Revert</button>
      <button type="button" class="save" :disabled="saving" @click="save">{{ saving ? 'Saving…' : 'Save' }}</button>
    </div>
    <ConfirmModal v-if="discardOpen" :open="discardOpen" title="Discard unsaved settings?" message="Your settings changes have not been saved." confirm-label="Discard changes" @confirm="answerDiscard(true)" @close="answerDiscard(false)" />
  </section>
</template>

<style scoped>
.settings-controls:disabled { pointer-events: none; }
.settings-controls { padding: 0; margin: 0; min-width: 0; border: none; }
.settings-view.dirty .column { padding-bottom: 110px; }
.settings-save-bar { position: fixed; bottom: 0; left: 52px; right: 0; z-index: 25; display: flex; align-items: center; gap: 12px; padding: 14px 32px; border-top: 1px solid var(--border); background: var(--surface); }
.settings-save-bar > div { flex: 1; min-width: 0; font-size: .9em; }
.settings-save-bar button { padding: 8px 20px; border: 1px solid var(--border); border-radius: var(--radius-full); color: var(--text); background: transparent; cursor: pointer; font: inherit; }
.settings-save-bar button.save { border-color: var(--accent); background: var(--accent); color: var(--accent-contrast); font-weight: 600; }
.save-error { margin: 4px 0 0; color: var(--danger); }
@media (max-width: 767px) { .settings-save-bar { left: 0; bottom: var(--rail-height); padding: 12px 16px; gap: 8px; } }

.settings-view {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.column {
  display: flex;
  flex-direction: column;
  gap: 16px;



}
.head {
  display: flex;
  align-items: center;
  gap: 12px;
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
