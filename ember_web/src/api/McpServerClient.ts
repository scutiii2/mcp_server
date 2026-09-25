import { McpClientBase } from "./McpClientBase";
import type { ToolInfo } from "./types";

/** mcp_server's MCP surface as ember_web uses it. Holds no secrets: never
 * the internal API token, which must stay server-side. */
export class McpServerClient extends McpClientBase {
  /** Every tool mcp_server currently exposes, following pagination. */
  async listTools(): Promise<ToolInfo[]> {
    const client = await this.session();
    const tools: ToolInfo[] = [];
    let cursor: string | undefined;
    do {
      const page = await client.listTools(cursor ? { cursor } : undefined);
      for (const t of page.tools) tools.push({ name: t.name, description: t.description ?? "" });
      cursor = page.nextCursor;
    } while (cursor);
    return tools;
  }
}
