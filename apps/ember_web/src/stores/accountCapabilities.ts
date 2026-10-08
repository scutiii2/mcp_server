import { defineStore } from "pinia";
import { ref, watch } from "vue";
import {
  accountCapabilitiesClient,
  type AccountCapabilities,
  type AccountItemKind,
} from "../api/AccountCapabilitiesClient";
import { errorMessage } from "../utils/errors";
import { useAuthStore } from "./auth";

function toggled(list: readonly string[], key: string, on: boolean): string[] {
  const next = new Set(list);
  if (on) next.add(key);
  else next.delete(key);
  return [...next].sort();
}

/** The built-in capabilities and server-listed extensions this account has
 * added, kept in ember_api. Loaded at login and dropped when the account
 * changes. `ready` is true only while what is shown is what ember_api last
 * said: nothing is assumed on a failed load, and chat waits for it before
 * sending. A change shows at once and is saved in the background, one save at
 * a time and in order; if a save fails, the server's copy is loaded back and
 * `error` says why. `settled()` resolves when every started load or save has
 * finished. */
export const useAccountCapabilitiesStore = defineStore("accountCapabilities", () => {
  const auth = useAuthStore();

  const capabilities = ref<string[]>([]);
  const extensions = ref<string[]>([]);
  // Tool names of every capability not added: sent with each question.
  const disabledTools = ref<string[]>([]);
  const ready = ref(false);
  const error = ref("");
  // Bumped on every account change: answers for the previous account are ignored.
  let generation = 0;
  // The newest change; only its save's answer may replace the lists.
  let latest = 0;
  let chain: Promise<void> = Promise.resolve();

  function apply(state: AccountCapabilities): void {
    capabilities.value = state.capabilities;
    extensions.value = state.extensions;
    disabledTools.value = state.disabled_tools;
  }

  async function load(): Promise<void> {
    const started = generation;
    try {
      const loaded = await accountCapabilitiesClient.get();
      if (started !== generation) return;
      apply(loaded);
      ready.value = true;
      error.value = "";
    } catch (err) {
      if (started !== generation) return;
      ready.value = false;
      error.value = errorMessage(err);
    }
  }

  watch(
    () => auth.account?.id ?? null,
    (id) => {
      generation += 1;
      capabilities.value = [];
      extensions.value = [];
      disabledTools.value = [];
      ready.value = false;
      error.value = "";
      chain = id !== null ? load() : Promise.resolve();
    },
    { immediate: true },
  );

  function change(kind: AccountItemKind, key: string, on: boolean): Promise<void> {
    const started = generation;
    const mine = ++latest;
    const list = kind === "capability" ? capabilities : extensions;
    list.value = toggled(list.value, key, on);
    error.value = "";
    chain = chain.then(async () => {
      if (started !== generation) return;
      try {
        const saved = await accountCapabilitiesClient.set(kind, key, on);
        if (started === generation && mine === latest) {
          apply(saved);
          ready.value = true;
        }
      } catch (err) {
        if (started !== generation) return;
        const message = errorMessage(err);
        await load();
        error.value = message;
      }
    });
    return chain;
  }

  /** Adds (true) or removes (false) built-in capability `name`. */
  function setCapability(name: string, on: boolean): Promise<void> {
    return change("capability", name, on);
  }

  /** Adds (true) or removes (false) server-listed extension `id`. */
  function setExtension(id: string, on: boolean): Promise<void> {
    return change("extension", id, on);
  }

  /** Reads the server's copy again (after an extension was removed). */
  function refresh(): Promise<void> {
    chain = chain.then(load);
    return chain;
  }

  function settled(): Promise<void> {
    return chain;
  }

  return { capabilities, extensions, disabledTools, ready, error, setCapability, setExtension, refresh, settled };
});
