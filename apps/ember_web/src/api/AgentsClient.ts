import { apiRequest } from "./http";

/** running: registered with ai_agent; offline: defined in agents/ but not
 * running; disabled: switched off in its agent file. */
export type AgentStatus = "running" | "offline" | "disabled";

/** One agent as ember_api's GET /api/agents returns it. No URL: where the
 * agents live stays server-side. */
export interface AgentListing {
  id: string;
  label: string;
  entry: boolean;
  orchestrator: boolean;
  focus: string;
  status: AgentStatus;
  /** From the agent's `llm` block; null when the agent file does not set it. */
  provider: string | null;
  gateway: string | null;
  model: string | null;
}

export const agentsClient = {
  list: () => apiRequest<AgentListing[]>("GET", "/api/agents"),
};
