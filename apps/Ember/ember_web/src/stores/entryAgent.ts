import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import { AiAgentClient } from "../api/AiAgentClient";
import { apiRequest, ApiError } from "../api/http";
import type { AgentInfo } from "../api/types";
import { useAuthStore } from "./auth";

/** The agent ember_api sends every question to (the main agent), for the
 * header and for naming answers. The browser never chooses an agent. */
export const useEntryAgentStore = defineStore("entryAgent", () => {
  const auth = useAuthStore();

  const entry = ref<AgentInfo | null>(null);
  const available = ref<boolean | null>(null); // null = not checked yet
  const loading = ref(false);
  const loadError = ref("");

  const labels = computed<Record<string, string>>(() => (entry.value ? { [entry.value.id]: entry.value.label } : {}));

  async function checkStatus(agent: AgentInfo): Promise<void> {
    try {
      available.value = (await new AiAgentClient(agent.id).status()).available !== false;
    } catch {
      available.value = false; // not running, or unreachable
    }
  }

  async function refresh(): Promise<void> {
    if (loading.value) return;
    loading.value = true;
    loadError.value = "";
    try {
      entry.value = await apiRequest<AgentInfo>("GET", "/api/agent");
    } catch (err) {
      entry.value = null;
      available.value = null;
      loadError.value = err instanceof ApiError || err instanceof Error ? err.message : String(err);
    } finally {
      loading.value = false;
    }
    if (entry.value) await checkStatus(entry.value);
  }

  // Another user (or the same one once verified) may have different permissions.
  watch(
    () => `${auth.account?.id ?? ""}:${auth.account?.email_verified ?? ""}`,
    () => {
      entry.value = null;
      available.value = null;
      loadError.value = "";
      if (auth.hasPermission("chat.use")) void refresh();
    },
  );

  return { entry, available, labels, loading, loadError, refresh };
});
