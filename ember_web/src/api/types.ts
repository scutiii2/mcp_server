/** One chat turn as ai_agent's ask() expects it in `history`. */
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

/** Live events ai_agent relays as MCP progress messages during ask(). */
export type AgentEvent =
  | { type: "token"; text: string }
  | { type: "token_reset" }
  | {
      type: "step_start";
      id: string;
      tool: string;
      label?: string;
      arguments: unknown;
    }
  | { type: "step_progress"; id: string; message: string }
  | { type: "step_end"; id: string; ok: boolean; result: string }
  | { type: "usage"; total_tokens: number; estimated: boolean };

/** ask()'s final result (only the fields ember_web uses so far). */
export interface AskResult {
  response: string;
  tools_used: string[];
  total_tokens: number | null;
  cancelled: boolean;
}

/** One mcp_server tool as the Tools page lists it. */
export interface ToolInfo {
  name: string;
  description: string;
}

/** One saved chat: its turns plus sidebar metadata. Times are epoch ms. */
export interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: number;
  updatedAt: number;
}
