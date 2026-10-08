<script setup lang="ts">
import { computed, ref } from "vue";
import SettingRow from "../components/SettingRow.vue";
import SidebarEditor from "../components/SidebarEditor.vue";
import SegmentedControl from "../components/SegmentedControl.vue";
import { DEFAULT_THEME, useTheme, type Theme } from "../composables/useTheme";
import { useNavPrefsStore } from "../stores/navPrefs";
import { isDefault } from "../utils/navArrangement";

const { theme, setTheme } = useTheme();
const navPrefs = useNavPrefsStore();
const query = ref("");
const onlyModified = ref(false);
const options: { value: Theme; label: string }[] = [
  { value: "system", label: "System" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" },
];
const themeModified = computed(() => theme.value !== DEFAULT_THEME);
const sidebarModified = computed(() => !isDefault(navPrefs.prefs));
const count = computed(() => Number(themeModified.value) + Number(sidebarModified.value));
function matches(words: string): boolean {
  return query.value.toLowerCase().trim().split(/\s+/).every(word => words.includes(word));
}
const showTheme = computed(() => matches("appearance theme light dark system color") && (!onlyModified.value || themeModified.value));
const showSidebar = computed(() => matches("sidebar pages order pin hide navigation rearrange drag") && (!onlyModified.value || sidebarModified.value));
</script>

<template>
  <section class="settings-view">
    <div class="column page-column">
      <header><h2 class="page-title">Settings</h2><p class="page-description">Adjust appearance and navigation preferences for Ember Admin.</p></header>
      <p class="scope">Applies instantly. Saved on this device. Sidebar preferences are separate for each account and from Ember Web.</p>
      <div class="search-bar">
        <input v-model="query" type="search" aria-label="Search settings" placeholder="Search settings" @keydown.esc="query = ''" />
        <button v-if="count || onlyModified" type="button" :aria-pressed="onlyModified" @click="onlyModified = !onlyModified">{{ count }} modified</button>
      </div>
      <section v-if="showTheme" aria-label="Appearance">
        <h3>Appearance</h3>
        <div class="card"><SettingRow setting-id="appearance-theme" label="Theme" description="Light, dark, or follow your system." :modified="themeModified" @reset="setTheme(DEFAULT_THEME)">
          <SegmentedControl :model-value="theme" :options="options" aria-label="Theme" @update:model-value="setTheme" />
        </SettingRow></div>
      </section>
      <section v-if="showSidebar" aria-label="Sidebar"><h3>Sidebar</h3><div class="card"><SidebarEditor /></div></section>
      <p v-if="!showTheme && !showSidebar" class="scope">No settings match your filters. <button type="button" @click="query = ''; onlyModified = false">Clear filters</button></p>
    </div>
  </section>
</template>

<style scoped>
.settings-view { flex: 1; min-height: 0; overflow-y: auto; }
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
