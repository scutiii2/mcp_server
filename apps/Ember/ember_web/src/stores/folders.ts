import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import { foldersClient, type ChatFolder } from "../api/FoldersClient";
import { ApiError } from "../api/http";
import { errorMessage } from "../utils/errors";
import { useAuthStore } from "./auth";
import { useChatStore } from "./chat";

const byPosition = (a: ChatFolder, b: ChatFolder) => a.position - b.position || a.id - b.id;

/** The account's chat folders. Loaded on first use and dropped when the user
 * changes (same pattern as the templates store). create / rename / reorder /
 * remove throw ember_api's error message so the dialog that called them can
 * show it. Which chat sits in which folder lives on the chat (`folderId`), in
 * the chat store. */
export const useFoldersStore = defineStore("folders", () => {
  const auth = useAuthStore();

  const items = ref<ChatFolder[]>([]);
  const loading = ref(false);
  const loadError = ref("");
  let loaded = false;
  // The load in progress, so a second ask waits for it instead of returning early.
  let inflight: Promise<void> | null = null;
  // Bumped on every account change: a load started for the previous account
  // is ignored when it arrives.
  let generation = 0;

  /** In display order. */
  const folders = computed(() => [...items.value].sort(byPosition));

  watch(
    () => (auth.hasPermission("chat.use") ? (auth.account?.id ?? null) : null),
    () => {
      generation += 1;
      items.value = [];
      loaded = false;
      inflight = null;
      loading.value = false;
      loadError.value = "";
    },
  );

  /** Loads the list once; a failed load can be retried by calling this again.
   * Asked while a load is running, it waits for that load. */
  function ensureLoaded(): Promise<void> {
    if (loaded || !auth.hasPermission("chat.use")) return Promise.resolve();
    if (inflight) return inflight;
    const started = generation;
    const run = reload().finally(() => {
      if (inflight === run && started === generation) inflight = null;
    });
    inflight = run;
    return run;
  }

  async function reload(): Promise<void> {
    const started = generation;
    loading.value = true;
    loadError.value = "";
    try {
      const list = await foldersClient.list();
      if (started !== generation) return;
      items.value = list;
      loaded = true;
    } catch (err) {
      if (started === generation) loadError.value = errorMessage(err);
    } finally {
      if (started === generation) loading.value = false;
    }
  }

  function upsert(folder: ChatFolder): void {
    items.value = [...items.value.filter((f) => f.id !== folder.id), folder];
  }

  async function create(name: string): Promise<ChatFolder> {
    const started = generation;
    const folder = await foldersClient.create(name);
    if (started === generation) upsert(folder);
    return folder;
  }

  async function rename(id: number, name: string): Promise<ChatFolder> {
    const started = generation;
    const folder = await foldersClient.rename(id, name);
    if (started === generation) upsert(folder);
    return folder;
  }

  async function reorder(id: number, position: number): Promise<ChatFolder> {
    const started = generation;
    const folder = await foldersClient.reorder(id, position);
    if (started === generation) upsert(folder);
    return folder;
  }

  /** Deletes the folder and, on the server, every chat in it; the chat store
   * then drops those chats from the screen. A folder that is already gone
   * (404, another tab) is treated as deleted. A 409 (a chat in it is
   * answering) leaves everything as it was and throws. */
  async function remove(id: number): Promise<void> {
    const started = generation;
    try {
      await foldersClient.remove(id);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) throw err;
    }
    if (started !== generation) return;
    items.value = items.value.filter((f) => f.id !== id);
    useChatStore().forgetFolder(id);
  }

  return { folders, loading, loadError, ensureLoaded, reload, create, rename, reorder, remove };
});
