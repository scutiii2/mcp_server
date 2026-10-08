import { apiRequest } from "./http";

export interface GatewayInfo {
  id: string;
  label: string;
  model: string;
  tiers: { tier: string; id: string }[];
}

/** Provider id -> the gateways it can run through (from ai_agent's config_gateways.json). */
export type ProviderCatalog = Record<string, GatewayInfo[]>;

export interface AgentLlm {
  provider: string;
  gateway?: string;
  model?: string;
  reasoning_effort?: string;
  temperature?: number;
  max_tokens?: number;
  max_tool_rounds?: number;
  max_effort?: string;
  min_tier?: string;
  max_tier?: string;
  [key: string]: unknown;
}

/** An agent file's content. Fields the form does not edit are kept as they are. */
export interface AgentConfig {
  label?: string;
  port: number;
  /** Address peers and ember_api reach the agent at; unset = http://127.0.0.1:<port>/mcp. */
  url?: string;
  enabled?: boolean;
  entry?: boolean;
  orchestrator?: boolean;
  llm: AgentLlm;
  persona?: string;
  instructions?: string;
  focus?: string;
  /** Replaces the shared identity line for this agent. */
  identity?: string;
  routing?: { laya?: boolean; top_k?: number; allow_auto?: boolean; min_score?: number };
  tools?: { allow?: string[]; deny?: string[] };
  [key: string]: unknown;
}

/** A listed agent: its file plus the id; a file ai_agent could not read has only `error`. */
export type AgentFile = Partial<AgentConfig> & { id: string; error?: string };

export type AgentStatus = "running" | "offline" | "disabled";

/** A model an agent may run on: its strength tier, model id and what the tier is for. */
export interface AgentTier {
  tier: string;
  id: string;
  use_for: string;
}

/** What ember_api reports about an agent right now. */
export interface LiveAgent {
  status: AgentStatus;
  tiers: AgentTier[];
}

/** The prompt texts every agent shares. `overridden` lists the ones that differ from the built-in default. */
export interface SharedPrompts {
  values: Record<string, string>;
  defaults: Record<string, string>;
  overridden: string[];
}

/** ember_api's /api/admin/agents (needs agents.manage), which ai_agent validates and applies. */
export const agentsAdminClient = {
  gateways: async () => (await apiRequest<{ providers: ProviderCatalog }>("GET", "/api/admin/agents/gateways")).providers,
  list: async () => (await apiRequest<{ agents: AgentFile[] }>("GET", "/api/admin/agents")).agents,
  create: (id: string, config: AgentConfig) => apiRequest<AgentFile>("POST", "/api/admin/agents", { id, config }),
  update: (id: string, config: AgentConfig) => apiRequest<AgentFile>("PUT", `/api/admin/agents/${encodeURIComponent(id)}`, { config }),
  remove: (id: string) => apiRequest<void>("DELETE", `/api/admin/agents/${encodeURIComponent(id)}`),
  prompts: () => apiRequest<SharedPrompts>("GET", "/api/admin/agent-prompts"),
  /** `null` (or blank) resets a text to its default. ai_agent restarts every agent to apply it. */
  setPrompts: (changes: Record<string, string | null>) => apiRequest<SharedPrompts>("PUT", "/api/admin/agent-prompts", changes),
  /** The assembled system prompt a draft agent file would get. */
  previewPrompt: async (id: string, config: AgentConfig, caveman: boolean) =>
    (await apiRequest<{ prompt: string }>("POST", "/api/admin/agent-prompt-preview", { id, config, caveman })).prompt,
  /** Status and effective model tiers by agent id (needs chat.use; callers treat a failure as "unknown"). */
  live: async (): Promise<Record<string, LiveAgent>> => {
    const rows = await apiRequest<({ id: string } & LiveAgent)[]>("GET", "/api/agents");
    return Object.fromEntries(rows.map((r) => [r.id, { status: r.status, tiers: r.tiers ?? [] }]));
  },
};
