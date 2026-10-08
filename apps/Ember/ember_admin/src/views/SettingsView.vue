<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import SettingRow from "../components/SettingRow.vue";
import SidebarEditor from "../components/SidebarEditor.vue";
import SegmentedControl from "../components/SegmentedControl.vue";
import { DEFAULT_THEME, useTheme, type Theme } from "../composables/useTheme";
import { useNavPrefsStore } from "../stores/navPrefs";
import { useAuthStore } from "../stores/auth";
import { isDefault } from "../utils/navArrangement";

const { theme, setTheme } = useTheme();
const navPrefs = useNavPrefsStore();
const auth = useAuthStore();
const saved = computed(() => ({
  theme: theme.value,
  sidebar: { order: [...navPrefs.prefs.order], pinned: [...navPrefs.prefs.pinned], hidden: [...navPrefs.prefs.hidden] },
}));
const draft = ref(structuredClone(saved.value));
const dirty = computed(() => JSON.stringify(draft.value) !== JSON.stringify(saved.value));
watch(saved, (next, previous) => {
  if (draft.value.theme === previous.theme) draft.value.theme = next.theme;
  if (JSON.stringify(draft.value.sidebar) === JSON.stringify(previous.sidebar)) {
    draft.value.sidebar = structuredClone(next.sidebar);
  }
});
function revert(): void { draft.value = structuredClone(saved.value); }
function save(): void {
  if (!dirty.value) return;
  if (JSON.stringify(draft.value.sidebar) !== JSON.stringify(saved.value.sidebar)) navPrefs.update(draft.value.sidebar);
  setTheme(draft.value.theme);
  revert();
}
watch(() => auth.account?.id, revert);
const discardOpen = ref(false);
let discardAnswer: ((discard: boolean) => void) | null = null;
function answerDiscard(discard: boolean): void {
  if (discard) revert();
  discardOpen.value = false;
  discardAnswer?.(discard);
  discardAnswer = null;
}
onBeforeRouteLeave(() => {
  if (!dirty.value) return true;
  discardOpen.value = true;
  return new Promise<boolean>(resolve => { discardAnswer = resolve; });
});
function beforeUnload(event: BeforeUnloadEvent): void {
  if (dirty.value) { event.preventDefault(); event.returnValue = ""; }
}
onMounted(() => window.addEventListener("beforeunload", beforeUnload));
onUnmounted(() => { window.removeEventListener("beforeunload", beforeUnload); answerDiscard(false); });
const query = ref("");
const onlyModified = ref(false);
const options: { value: Theme; label: string }[] = [
  { value: "system", label: "System" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" },
];
const themeModified = computed(() => draft.value.theme !== DEFAULT_THEME);
const sidebarModified = computed(() => !isDefault(draft.value.sidebar));
const count = computed(() => Number(themeModified.value) + Number(sidebarModified.value));
function matches(words: string): boolean {
  return query.value.toLowerCase().trim().split(/\s+/).every(word => words.includes(word));
}
const showTheme = computed(() => matches("appearance theme light dark system color") && (!onlyModified.value || themeModified.value));
const showSidebar = computed(() => matches("sidebar pages order pin hide navigation rearrange drag") && (!onlyModified.value || sidebarModified.value));
</script>

<template>
  <section class="settings-view" :class="{ dirty }">
    <div class="column page-column">
      <header><h2 class="page-title">Settings</h2><p class="page-description">Adjust appearance and navigation preferences for Ember Admin.</p></header>
      <p class="scope">Applied when you save. Stored on this device. Sidebar preferences are separate for each account and from Ember Web.</p>
      <p v-if="navPrefs.error" class="save-error" role="alert">{{ navPrefs.error }}</p>
      <div class="search-bar">
        <input v-model="query" type="search" aria-label="Search settings" placeholder="Search settings" @keydown.esc="query = ''" />
        <button v-if="count || onlyModified" type="button" :aria-pressed="onlyModified" @click="onlyModified = !onlyModified">{{ count }} modified</button>
      </div>
      <section v-if="showTheme" aria-label="Appearance">
        <h3>Appearance</h3>
        <div class="card"><SettingRow setting-id="appearance-theme" label="Theme" description="Light, dark, or follow your system." :modified="themeModified" @reset="draft.theme = DEFAULT_THEME">
          <SegmentedControl v-model="draft.theme" :options="options" aria-label="Theme" />
        </SettingRow></div>
      </section>
      <section v-if="showSidebar" aria-label="Sidebar"><h3>Sidebar</h3><div class="card"><SidebarEditor v-model="draft.sidebar" /></div></section>
      <p v-if="!showTheme && !showSidebar" class="scope">No settings match your filters. <button type="button" @click="query = ''; onlyModified = false">Clear filters</button></p>
    </div>
    <div v-if="dirty" class="settings-save-bar" role="group" aria-label="Unsaved settings">
      <span>Unsaved changes</span>
      <button type="button" class="revert" @click="revert">Revert</button>
      <button type="button" class="save" @click="save">Save</button>
    </div>
    <ConfirmModal v-if="discardOpen" :open="discardOpen" title="Discard unsaved settings?" message="Your settings changes have not been saved." confirm-label="Discard changes" @confirm="answerDiscard(true)" @close="answerDiscard(false)" />
  </section>
</template>

<style scoped>
.settings-view { flex: 1; min-height: 0; overflow-y: auto; }
.settings-view.dirty .column { padding-bottom: 110px; }
.settings-save-bar { position: fixed; bottom: 0; left: 52px; right: 0; z-index: 25; display: flex; align-items: center; gap: 12px; padding: 14px 32px; border-top: 1px solid var(--border); background: var(--surface); }
.settings-save-bar > span { flex: 1; min-width: 0; }
.settings-save-bar button { padding: 8px 20px; color: var(--text); }
.settings-save-bar button.save { background: var(--accent); border-color: var(--accent); color: var(--accent-contrast); font-weight: 600; }
.save-error { margin: 0; color: var(--danger); }
@media (max-width: 767px) { .settings-save-bar { left: 0; bottom: var(--rail-height); padding: 12px 16px; gap: 8px; } }
.column { display: flex; flex-direction: column; gap: 16px; }
.scope { margin: 0; color: var(--muted); font-size: .9em; }
h3 { margin: 0 0 8px; font-size: 1em; }
.card { padding: 4px 16px 6px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface); }
.search-bar { display: flex; gap: 8px; flex-wrap: wrap; }
input { flex: 1; min-width: 160px; padding: 8px 12px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg); color: var(--text); font: inherit; }
button { padding: 6px 12px; border: 1px solid var(--border); border-radius: var(--radius-full); background: transparent; color: var(--accent); cursor: pointer; font: inherit; }
button[aria-pressed="true"] { background: var(--accent); color: var(--accent-contrast); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
</style>
