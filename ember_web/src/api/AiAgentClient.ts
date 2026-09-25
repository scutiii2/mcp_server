import { McpClientBase } from "./McpClientBase";
import type { AgentEvent, AskResult, ChatMessage } from "./types";

/** One ai_agent instance's MCP tools (status, ask streamed, cancel), via
 * ember_api's /api/mcp/agents/{id} proxy. */
export class AiAgentClient extends McpClientBase {
  constructor(agentId: string) {
    super(`/api/mcp/agents/${encodeURIComponent(agentId)}`);
  }

  /** ai_agent's status tool: provider availability. */
  async status(): Promise<Record<string, unknown>> {
    return this.callTool("status", {});
  }

  /** Runs one chat turn; streams live events to onEvent, resolves with the
   * final answer. requestId is what cancel() stops it by. */
  async ask(
    question: string,
    history: ChatMessage[],
    requestId: string,
    onEvent: (event: AgentEvent) => void,
  ): Promise<AskResult> {
    const result = await this.callTool(
      "ask",
      { question, history, request_id: requestId },
      {
        onprogress: (progress) => {
          if (progress.message)
            onEvent(JSON.parse(progress.message) as AgentEvent);
        },
        // A long tool-calling turn can pass the SDK's 60s default; every
        // progress event restarts the clock instead.
        resetTimeoutOnProgress: true,
      },
    );
    return result as unknown as AskResult;
  }

  /** Asks ai_agent to stop the ask() with this requestId. Cooperative: it
   * takes effect at the turn's next round, not instantly. */
  async cancel(requestId: string): Promise<boolean> {
    const result = await this.callTool("cancel", { request_id: requestId });
    return result.cancelled === true;
  }
}
