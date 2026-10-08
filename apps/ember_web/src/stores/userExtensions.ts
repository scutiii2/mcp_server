import { defineStore } from "pinia";
import { ref, watch } from "vue";
import {
  userExtensionsClient,
  type UserExtension,
  type UserExtensionInput,
  type UserExtensionPatch,
} from "../api/UserExtensionsClient";
import { errorMessage } from "../utils/errors";
import { useAuthStore } from "./auth";

/** The account's own MCP servers ("private extensions"), kept in ember_api.
 * Loaded at sign-in for accounts with chat.use and dropped when the account
 * changes; the Supermarket and the Capabilities page call `refresh()` when they
 * open, because each one's status comes from a live probe. `add`, `update` and
 * `remove` let the API's error propagate (the modal shows it); `setEnabled`
 * shows the change at once and rolls it back, with `error`, if the save fails. */
export const useUserExtensionsStore = defineStore("userExtensions", () => {
  const auth = useAuthStore();

  const items = ref<UserExtension[]>([]);
  const ready = ref(false);
  const error = ref("");
  // Bumped on every account change: answers for the previous account are ignored.
  let generation = 0;

  async function refresh(): Promise<void> {
    const started = generation;
    try {
      const list = await userExtensionsClient.list();
      if (started !== generation) return;
      items.value = list;
      ready.value = true;
      error.value = "";
    } catch (err) {
      if (started === generation) error.value = errorMessage(err);
    }
  }

  watch(
    () => (auth.hasPermission("chat.use") ? (auth.account?.id ?? null) : null),
    (id) => {
      generation += 1;
      items.value = [];
      ready.value = false;
      error.value = "";
      if (id !== null) void refresh();
    },
    { immediate: true },
  );

  function put(item: UserExtension): void {
    const index = items.value.findIndex((i) => i.id === item.id);
    if (index === -1) items.value = [...items.value, item];
    else items.value = items.value.map((i) => (i.id === item.id ? item : i));
  }

  async function add(input: UserExtensionInput): Promise<UserExtension> {
    const started = generation;
    const created = await userExtensionsClient.create(input);
    if (started === generation) put(created);
    return created;
  }

  async function update(id: string, patch: UserExtensionPatch): Promise<UserExtension> {
    const started = generation;
    const updated = await userExtensionsClient.update(id, patch);
    if (started === generation) put(updated);
    return updated;
  }

  async function remove(id: string): Promise<void> {
    const started = generation;
    await userExtensionsClient.remove(id);
    if (started === generation) items.value = items.value.filter((i) => i.id !== id);
  }

  async function setEnabled(id: string, on: boolean): Promise<void> {
    const started = generation;
    const before = items.value.find((i) => i.id === id);
    if (!before) return;
    error.value = "";
    put({ ...before, enabled: on });
    try {
      const updated = await userExtensionsClient.update(id, { enabled: on });
      if (started === generation) put(updated);
    } catch (err) {
      if (started !== generation) return;
      put(before);
      error.value = errorMessage(err);
    }
  }

  return { items, ready, error, refresh, add, update, remove, setEnabled };
});
