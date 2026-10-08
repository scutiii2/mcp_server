import { defineStore } from "pinia";
import { ref, watch } from "vue";
import { useAuthStore } from "./auth";

export interface NavPrefs { order: string[]; pinned: string[]; hidden: string[] }
const empty = (): NavPrefs => ({ order: [], pinned: [], hidden: [] });

/** Admin layout is private to this account and browser, separate from Ember Web. */
export const useNavPrefsStore = defineStore("adminNavPrefs", () => {
  const auth = useAuthStore();
  const prefs = ref<NavPrefs>(empty());
  const error = ref("");
  watch(() => auth.account?.id, (id) => {
    prefs.value = empty();
    error.value = "";
    if (id == null) return;
    try {
      const saved: unknown = JSON.parse(localStorage.getItem(`ember_admin.nav.${id}`) ?? "null");
      if (saved && typeof saved === "object" && ["order", "pinned", "hidden"].every(k =>
        Array.isArray((saved as Record<string, unknown>)[k]) &&
        ((saved as Record<string, unknown>)[k] as unknown[]).every(v => typeof v === "string"))) {
        prefs.value = saved as NavPrefs;
      }
    } catch { /* Unavailable or invalid storage uses the default layout. */ }
  }, { immediate: true });
  function update(next: NavPrefs): void {
    if (!auth.account) return;
    prefs.value = { order: [...next.order], pinned: [...next.pinned], hidden: [...next.hidden] };
    error.value = "";
    try { localStorage.setItem(`ember_admin.nav.${auth.account.id}`, JSON.stringify(prefs.value)); }
    catch { error.value = "Applied for this session, but this browser could not save your sidebar preferences."; }
  }
  function reset(): void { update(empty()); }
  return { prefs, error, update, reset };
});
