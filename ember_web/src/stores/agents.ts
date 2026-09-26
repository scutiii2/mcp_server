import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import { AiAgentClient } from "../api/AiAgentClient";
import { apiRequest } from "../api/http";
import type { AgentInfo } from "../api/types";
import { useAuthStore } from "./auth";

const SELECTED_KEY = "ember_web.agent";

// Per-viewer convenience only: blocked storage just means the first agent.
function readSelected(): string | null {
  try {
    return localStorage.getItem(SELECTED_KEY);
  } catch {
    return null;
  }
}

function writeSelected(id: string): void {
  try {
    localStorage.setItem(SELECTED_KEY, id);
  } catch {
    // ignore - see readSelected
  }
}

/** Which ai_agent instances ember_api offers, which one is picked, and one
 * reusable MCP client (through ember_api's proxy) per agent. */
export const useAgentsStore = defineStore("agents", () => {
  const auth = useAuthStore();

  const agents = ref<AgentInfo[]>([]);
  const available = ref<Record<string, boolean>>({}); // missing = not checked yet
  const selectedId = ref<string | null>(readSelected());
  const loading = ref(false);
  const loadError = ref("");

  // Keyed by agent id so switching back and forth reuses the open MCP session.
  let clients = new Map<string, AiAgentClient>();

  function clientFor(agentId: string): AiAgentClient {
    let client = clients.get(agentId);
    if (!client) {
      client = new AiAgentClient(agentId);
      clients.set(agentId, client);
    }
    return client;
  }

  const selected = computed<AgentInfo | null>(
    () => agents.value.find((a) => a.id === selectedId.value) ?? agents.value[0] ?? null,
  );

  function select(id: string): void {
    if (!agents.value.some((a) => a.id === id)) return;
    selectedId.value = id;
    writeSelected(id);
  }

  async function checkStatus(agent: AgentInfo): Promise<void> {
    let ok = false;
    try {
      ok = (await clientFor(agent.id).status()).available !== false;
    } catch {
      ok = false; // not running, or unreachable
    }
    available.value = { ...available.value, [agent.id]: ok };
  }

  /** Reloads the list from ember_api, then checks every agent's status in parallel. */
  async function refresh(): Promise<void> {
    if (loading.value) return;
    loading.value = true;
    loadError.value = "";
    try {
      agents.value = await apiRequest<AgentInfo[]>("GET", "/api/agents");
    } catch (err) {
      agents.value = [];
      loadError.value = err instanceof Error ? err.message : String(err);
    } finally {
      loading.value = false;
    }
    available.value = {};
    await Promise.all(agents.value.map(checkStatus));
  }

  // A different (or no) user: drop the list and every MCP session, then
  // reload for the new user (their permissions may differ).
  // Keyed on verification too: verifying the email is what unlocks chat.use.
  watch(
    () => `${auth.account?.id ?? ""}:${auth.account?.email_verified ?? ""}`,
    () => {
      agents.value = [];
      available.value = {};
      clients = new Map();
      if (auth.hasPermission("chat.use")) void refresh();
    },
  );

  return { agents, available, selected, loading, loadError, select, refresh };
});
