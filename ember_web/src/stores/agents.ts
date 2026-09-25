import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { AiAgentClient } from "../api/AiAgentClient";
import type { AgentInfo } from "../api/types";

const SELECTED_KEY = "ember_web.agent";

// Per-viewer convenience only: blocked storage just means the default agent.
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

/** Which ai_agent instances exist, which one is picked, and one reusable
 * MCP client per instance. */
export const useAgentsStore = defineStore("agents", () => {
  // The agent ember_web is configured with: asked for the registry, and the
  // only choice when the registry is empty or unreachable.
  const fallback: AgentInfo = {
    id: "default",
    label: "Default agent",
    url: import.meta.env.VITE_AI_AGENT_URL,
  };

  const agents = ref<AgentInfo[]>([fallback]);
  const available = ref<Record<string, boolean>>({}); // missing = not checked yet
  const selectedId = ref<string | null>(readSelected());
  const loading = ref(false);

  // Keyed by URL so switching back and forth reuses the open MCP session.
  const clients = new Map<string, AiAgentClient>();

  function clientFor(url: string): AiAgentClient {
    let client = clients.get(url);
    if (!client) {
      client = new AiAgentClient(url);
      clients.set(url, client);
    }
    return client;
  }

  const selected = computed<AgentInfo>(
    () => agents.value.find((a) => a.id === selectedId.value) ?? agents.value[0] ?? fallback,
  );

  function select(id: string): void {
    if (!agents.value.some((a) => a.id === id)) return;
    selectedId.value = id;
    writeSelected(id);
  }

  /** The selected agent plus its client, captured together for one turn. */
  function current(): { agent: AgentInfo; client: AiAgentClient } {
    const agent = selected.value;
    return { agent, client: clientFor(agent.url) };
  }

  async function checkStatus(agent: AgentInfo): Promise<void> {
    let ok = false;
    try {
      ok = (await clientFor(agent.url).status()).available !== false;
    } catch {
      ok = false; // not running, or unreachable
    }
    available.value = { ...available.value, [agent.id]: ok };
  }

  /** Reloads the registry from the configured agent, then checks every
   * agent's status in parallel. */
  async function refresh(): Promise<void> {
    if (loading.value) return;
    loading.value = true;
    try {
      const list = await clientFor(fallback.url).listAgents();
      agents.value = list.length > 0 ? list : [fallback];
    } catch {
      agents.value = [fallback]; // e.g. an older ai_agent without list_agents
    } finally {
      loading.value = false;
    }
    available.value = {};
    await Promise.all(agents.value.map(checkStatus));
  }

  return { agents, available, selected, loading, select, current, refresh };
});
