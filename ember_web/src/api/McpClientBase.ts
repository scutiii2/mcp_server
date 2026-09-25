import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import type { RequestOptions } from "@modelcontextprotocol/sdk/shared/protocol.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

/** What Client.callTool resolves to. */
export type RawToolResult = Awaited<ReturnType<Client["callTool"]>>;

/** One lazily-opened MCP session to one server, reached through ember_api's
 * same-origin proxy (the session cookie rides along automatically);
 * subclasses add typed tool methods. */
export abstract class McpClientBase {
  private readonly path: string;
  private client: Client | null = null;
  private connecting: Promise<Client> | null = null;

  /** path: an ember_api proxy route, e.g. "/api/mcp/server". */
  constructor(path: string) {
    this.path = path;
  }

  /** Opens the session once. Concurrent first calls share one connect
   * instead of racing to open two sessions. */
  protected async session(): Promise<Client> {
    if (this.client) return this.client;
    this.connecting ??= this.open();
    try {
      this.client = await this.connecting;
      return this.client;
    } finally {
      this.connecting = null;
    }
  }

  private async open(): Promise<Client> {
    const client = new Client({ name: "ember_web", version: "0.1.0" });
    await client.connect(new StreamableHTTPClientTransport(new URL(this.path, window.location.origin)));
    return client;
  }

  /** Calls one tool and returns the full MCP result (content parts,
   * isError, structuredContent). */
  protected async callToolRaw(
    name: string,
    args: Record<string, unknown>,
    options?: RequestOptions,
  ): Promise<RawToolResult> {
    const client = await this.session();
    return client.callTool({ name, arguments: args }, undefined, options);
  }

  /** Calls one tool; FastMCP returns a dict result as structuredContent. */
  protected async callTool(
    name: string,
    args: Record<string, unknown>,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    const result = await this.callToolRaw(name, args, options);
    return (result.structuredContent ?? {}) as Record<string, unknown>;
  }
}
