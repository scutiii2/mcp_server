import { McpClientBase } from "./McpClientBase";
import { toolTitle } from "../utils/toolTitles";
import type { JsonSchema, ResourceInfo, ToolInfo, ToolRunResult } from "./types";

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

  /** Fixed-URI resources plus URI templates, following pagination. */
  async listResources(): Promise<ResourceInfo[]> {
    const client = await this.session();
    const found: ResourceInfo[] = [];
    let cursor: string | undefined;
    do {
      const page = await client.listResources(cursor ? { cursor } : undefined);
      for (const r of page.resources) {
        found.push({ uri: r.uri, name: r.name, description: r.description ?? "", template: false });
      }
      cursor = page.nextCursor;
    } while (cursor);
    do {
      const page = await client.listResourceTemplates(cursor ? { cursor } : undefined);
      for (const t of page.resourceTemplates) {
        found.push({ uri: t.uriTemplate, name: t.name, description: t.description ?? "", template: true });
      }
      cursor = page.nextCursor;
    } while (cursor);
    return found;
  }

  /** A resource's text parts, joined (binary parts are only named). */
  async readResource(uri: string): Promise<string> {
    const client = await this.session();
    const result = await client.readResource({ uri });
    return result.contents
      .map((c) => ("text" in c && typeof c.text === "string" ? c.text : `[binary ${c.mimeType ?? "content"}]`))
      .join("\n\n");
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
