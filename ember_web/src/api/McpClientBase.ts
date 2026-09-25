import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import type { RequestOptions } from "@modelcontextprotocol/sdk/shared/protocol.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

/** One lazily-opened MCP session to one server; subclasses add typed tool methods. */
export abstract class McpClientBase {
  private readonly url: string;
  private client: Client | null = null;
  private connecting: Promise<Client> | null = null;

  constructor(url: string) {
    this.url = url;
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
    await client.connect(new StreamableHTTPClientTransport(new URL(this.url)));
    return client;
  }

  /** Calls one tool; FastMCP returns a dict result as structuredContent. */
  protected async callTool(
    name: string,
    args: Record<string, unknown>,
    options?: RequestOptions,
  ): Promise<Record<string, unknown>> {
    const client = await this.session();
    const result = await client.callTool({ name, arguments: args }, undefined, options);
    return (result.structuredContent ?? {}) as Record<string, unknown>;
  }
}
