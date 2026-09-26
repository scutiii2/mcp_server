import { McpClientBase } from "./McpClientBase";

/** One ai_agent instance's availability check, via ember_api's
 * /api/mcp/agents/{id} proxy. Chat turns don't go through here: ember_api
 * runs them itself (see ChatsClient.startTurn), so they finish, are saved and
 * count toward the usage limits even if this page closes. */
export class AiAgentClient extends McpClientBase {
  constructor(agentId: string) {
    super(`/api/mcp/agents/${encodeURIComponent(agentId)}`);
  }

  /** ai_agent's status tool: provider availability. */
  async status(): Promise<Record<string, unknown>> {
    return this.callTool("status", {});
  }
}
