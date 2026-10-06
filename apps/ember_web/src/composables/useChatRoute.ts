import { ref, watch, type Ref } from "vue";
import { useRoute, useRouter } from "vue-router";

/** What the chat page needs from the chat store. */
export interface ChatRouteStore {
  activeId: Ref<string | null>;
  /** The chat list was fetched, so a missing id really is missing. */
  listReady: Ref<boolean>;
  hasChat: (id: string) => boolean;
  selectChat: (id: string, options?: { messageIndex?: number }) => Promise<void>;
  newChat: () => void;
  /** Re-reads the chat list. */
  reload: () => Promise<void>;
}

export function chatPath(id: string | null): string {
  return id === null ? "/" : `/chat/${encodeURIComponent(id)}`;
}

/**
 * Keeps the address bar and the open chat in step, so a chat can be
 * bookmarked, reloaded and reached with the back button.
 *
 * - `/chat/<id>` opens that chat; an id that isn't in the account's list
 *   goes back to `/` and sets `notFound`.
 * - Chats the user opens (`open`, `startNew`) are history entries. Changes
 *   nobody asked the address bar for (a new chat getting its id, the open
 *   chat deleted) replace the current entry instead, so back skips them.
 *
 * `isActive`: false while the page is cached behind another one (KeepAlive);
 * the address then belongs to that other page.
 */
export function useChatRoute(store: ChatRouteStore, isActive: Ref<boolean>) {
  const route = useRoute();
  const router = useRouter();
  const notFound = ref(false);
  // The path a navigation started here is heading for: the open-chat watcher
  // must not start a second one to the same place.
  let inflight: string | null = null;

  /** null: "/" (a fresh chat); undefined: not on a chat route at all. */
  function routeChatId(): string | null | undefined {
    if (route.name === "chat-id") return String(route.params.id);
    return route.name === "chat" ? null : undefined;
  }

  function navigate(path: string, mode: "push" | "replace"): void {
    if (route.path === path) return;
    inflight = path;
    void router[mode](path).finally(() => {
      if (inflight === path) inflight = null;
    });
  }

  /** The address changed (back, forward, a typed link): open what it names. */
  async function followRoute(): Promise<void> {
    if (!isActive.value) return;
    const id = routeChatId();
    if (id === undefined || id === store.activeId.value) return;
    if (id === null) {
      store.newChat();
      return;
    }
    if (!store.listReady.value) return; // runs again once the list is in
    if (!store.hasChat(id)) await store.reload(); // maybe made in another tab
    if (routeChatId() !== id) return; // the user moved on meanwhile
    if (store.hasChat(id)) {
      notFound.value = false;
      await store.selectChat(id);
    } else {
      notFound.value = true;
      navigate("/", "replace");
    }
  }

  watch(() => route.fullPath, () => void followRoute());
  watch(store.listReady, () => void followRoute());

  // The open chat changed some other way: show it in the address bar.
  watch(store.activeId, (id) => {
    if (!isActive.value || routeChatId() === undefined || !store.listReady.value) return;
    const path = chatPath(id);
    if (inflight === path) return;
    navigate(path, "replace");
  });

  /** A chat the user picked. */
  function open(id: string, options: { messageIndex?: number } = {}): void {
    notFound.value = false;
    void store.selectChat(id, options);
    navigate(chatPath(id), "push");
  }

  /** The user started a fresh chat. */
  function startNew(): void {
    notFound.value = false;
    store.newChat();
    navigate("/", "push");
  }

  /** The page was (re)shown: a bare `/` after a visit elsewhere keeps the
   * chat that was open rather than starting a new one. */
  function activate(): void {
    const id = routeChatId();
    if (id === null && store.activeId.value !== null) navigate(chatPath(store.activeId.value), "replace");
    else void followRoute();
  }

  return { notFound, open, startNew, activate };
}
