import { defineStore } from "pinia";
import { ref, watch } from "vue";
import { navPreferencesClient, type NavPrefs } from "../api/NavPreferencesClient";
import { errorMessage } from "../utils/errors";
import { EMPTY_PREFS } from "../utils/navArrangement";
import { useAuthStore } from "./auth";

/** How the account arranges its nav rail (order, pinned, hidden), kept in
 * ember_api. Loaded at login and dropped when the user changes. `update`
 * applies a change at once and saves it in the background, one save at a time
 * and in order; if a save fails, the server's copy is loaded back and `error`
 * says why. `ready` turns true once the first load has settled (even if it
 * failed), so the rail doesn't draw one order and then jump to another. */
export const useNavPrefsStore = defineStore("navPrefs", () => {
  const auth = useAuthStore();

  const prefs = ref<NavPrefs>(EMPTY_PREFS);
  const ready = ref(false);
  const error = ref("");
  // Bumped on every account change: answers for the previous account are ignored.
  let generation = 0;
  // The newest change; only its save's answer may replace `prefs`.
  let latest = 0;
  let chain: Promise<void> = Promise.resolve();

  async function load(): Promise<void> {
    const started = generation;
    try {
      const loaded = await navPreferencesClient.get();
      if (started === generation) prefs.value = loaded;
    } catch (err) {
      if (started === generation) error.value = errorMessage(err);
    } finally {
      if (started === generation) ready.value = true;
    }
  }

  watch(
    () => auth.account?.id ?? null,
    (id) => {
      generation += 1;
      prefs.value = EMPTY_PREFS;
      ready.value = false;
      error.value = "";
      chain = Promise.resolve();
      if (id !== null) void load();
    },
    { immediate: true },
  );

  /** Shows `next` now and saves it; resolves when the save has finished. */
  function update(next: NavPrefs): Promise<void> {
    const started = generation;
    const mine = ++latest;
    prefs.value = next;
    error.value = "";
    chain = chain.then(async () => {
      try {
        const saved = await navPreferencesClient.save(next);
        if (started === generation && mine === latest) prefs.value = saved;
      } catch (err) {
        if (started !== generation) return;
        error.value = errorMessage(err);
        await load();
      }
    });
    return chain;
  }

  /** Back to the default arrangement. */
  function reset(): Promise<void> {
    const started = generation;
    const mine = ++latest;
    prefs.value = EMPTY_PREFS;
    error.value = "";
    chain = chain.then(async () => {
      try {
        await navPreferencesClient.reset();
      } catch (err) {
        if (started !== generation) return;
        error.value = errorMessage(err);
        if (mine === latest) await load();
      }
    });
    return chain;
  }

  return { prefs, ready, error, update, reset };
});
