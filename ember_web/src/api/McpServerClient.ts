import { McpClientBase } from "./McpClientBase";
import { toolTitle } from "../utils/toolTitles";
import type { JsonSchema, ToolInfo, ToolRunResult } from "./types";

/** mcp_server's MCP surface as ember_web uses it, via ember_api's
 * /api/mcp/server proxy. Holds no secrets: ember_api adds identity and the
 * internal token server-side. */
export class McpServerClient extends McpClientBase {
  constructor() {
    super("/api/mcp/server");
  }

  /** Every tool mcp_server currently exposes, following pagination. */
  async listTools(): Promise<ToolInfo[]> {
    const client = await this.session();
    const tools: ToolInfo[] = [];
    let cursor: string | undefined;
    do {
      const page = await client.listTools(cursor ? { cursor } : undefined);
      for (const t of page.tools) {
        tools.push({
          name: t.name,
          title: t.title ?? t.annotations?.title ?? toolTitle(t.name),
          description: t.description ?? "",
          inputSchema: (t.inputSchema ?? {}) as JsonSchema,
        });
      }
      cursor = page.nextCursor;
    } while (cursor);
    return tools;
  }

  /** Runs one tool. A tool-side failure comes back as isError: true; only
   * transport/protocol failures throw. */
  async runTool(name: string, args: Record<string, unknown>): Promise<ToolRunResult> {
    const result = await this.callToolRaw(name, args);
    const parts = Array.isArray(result.content) ? result.content : [];
    const text = parts
      .map((part) => (part && typeof part === "object" && "text" in part ? String(part.text) : ""))
      .filter(Boolean)
      .join("\n\n");
    return {
      text,
      isError: result.isError === true,
      structured: (result.structuredContent ?? undefined) as Record<string, unknown> | undefined,
    };
  }
}
