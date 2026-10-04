import { defineStore } from "pinia";
import { ref, watch } from "vue";
import { ApiError } from "../api/http";
import { templatesClient, type PromptTemplate } from "../api/TemplatesClient";
import { errorMessage } from "../utils/errors";
import { useAuthStore } from "./auth";

/** The account's saved prompts. Loaded on first use (not at login: most
 * sessions never open the picker) and dropped when the user changes. The
 * create / update / remove actions throw ember_api's error message so the
 * dialog that called them can show it. */
export const useTemplatesStore = defineStore("templates", () => {
  const auth = useAuthStore();

  const templates = ref<PromptTemplate[]>([]);
  const loading = ref(false);
  const loadError = ref("");
  let loaded = false;
  // Bumped on every account change: a load started for the previous account
  // is ignored when it arrives.
  let generation = 0;

  watch(
    () => (auth.hasPermission("chat.use") ? (auth.account?.id ?? null) : null),
    () => {
      generation += 1;
      templates.value = [];
      loaded = false;
      loading.value = false;
      loadError.value = "";
    },
  );

  /** Loads the list once; a failed load can be retried by calling this again. */
  async function ensureLoaded(): Promise<void> {
    if (loaded || loading.value || !auth.hasPermission("chat.use")) return;
    await reload();
  }

  async function reload(): Promise<void> {
    const started = generation;
    loading.value = true;
    loadError.value = "";
    try {
      const list = await templatesClient.list();
      if (started !== generation) return;
      templates.value = list;
      loaded = true;
    } catch (err) {
      if (started === generation) loadError.value = errorMessage(err);
    } finally {
      if (started === generation) loading.value = false;
    }
  }

  /** Newest edit first, as ember_api lists them. */
  function upsert(template: PromptTemplate): void {
    templates.value = [template, ...templates.value.filter((t) => t.id !== template.id)];
  }

  async function create(name: string, body: string): Promise<PromptTemplate> {
    const started = generation;
    const template = await templatesClient.create(name, body);
    if (started === generation) upsert(template);
    return template;
  }

  async function update(id: number, name: string, body: string): Promise<PromptTemplate> {
    const started = generation;
    const template = await templatesClient.update(id, name, body);
    if (started === generation) upsert(template);
    return template;
  }

  async function remove(id: number): Promise<void> {
    const started = generation;
    try {
      await templatesClient.remove(id);
    } catch (err) {
      // Already gone (another tab): the list should agree with the server.
      if (!(err instanceof ApiError && err.status === 404)) throw err;
    }
    if (started === generation) templates.value = templates.value.filter((t) => t.id !== id);
  }

  return { templates, loading, loadError, ensureLoaded, reload, create, update, remove };
});
