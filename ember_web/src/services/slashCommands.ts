import { commandsClient, type CommandInfo, type HelpTarget } from "../api/CommandsClient";
import { McpServerClient } from "../api/McpServerClient";
import type { JsonSchema, ToolInfo } from "../api/types";
import { formatToolResult } from "../utils/toolResultFormat";

/** "/<capability> <command> key=value ..." runs an mcp_server tool directly,
 * no AI involved (port of chat_app's services/commands.py). "/help" and
 * "/<capability> help [target=...] [command=...]" show capability help.
 * Every failure a user can fix comes back as a "❌ ..." result, never thrown. */

export class CommandError extends Error {}

export interface ParsedCommand {
  capability: string;
  command: string;
  params: Record<string, string>;
}

const HELP_TARGETS: HelpTarget[] = ["all", "tools", "commands", "workflow"];

/** Shell-like split: spaces separate words, quotes group them. */
export function splitWords(text: string): string[] {
  const words: string[] = [];
  let current = "";
  let quote: '"' | "'" | null = null;
  let inWord = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i]!;
    if (quote) {
      if (ch === quote) quote = null;
      else if (ch === "\\" && quote === '"' && i + 1 < text.length) current += text[++i];
      else current += ch;
    } else if (ch === '"' || ch === "'") {
      quote = ch;
      inWord = true;
    } else if (/\s/.test(ch)) {
      if (inWord) words.push(current);
      current = "";
      inWord = false;
    } else {
      current += ch;
      inWord = true;
    }
  }
  if (quote) throw new CommandError("Unbalanced quotes");
  if (inWord) words.push(current);
  return words;
}

export function parseCommand(text: string): ParsedCommand {
  const words = splitWords(text.replace(/^\//, ""));
  if (words.length < 2) {
    throw new CommandError("A command needs a capability and a command: /<capability> <command> [key=value ...]");
  }
  const [capability, command, ...rest] = words as [string, string, ...string[]];
  const params: Record<string, string> = {};
  for (const word of rest) {
    const eq = word.indexOf("=");
    if (eq <= 0) throw new CommandError(`Expected key=value, got "${word}"`);
    params[word.slice(0, eq)] = word.slice(eq + 1);
  }
  return { capability, command, params };
}

function typeOf(schema: JsonSchema): string {
  const branch = schema.anyOf?.find((s) => s.type !== "null") ?? schema;
  const type = Array.isArray(branch.type) ? branch.type.find((t) => t !== "null") : branch.type;
  return type ?? "string";
}

function coerce(name: string, value: string, schema: JsonSchema): unknown {
  switch (typeOf(schema)) {
    case "integer": {
      if (!/^-?\d+$/.test(value)) throw new CommandError(`"${name}" must be an integer, got "${value}"`);
      return Number(value);
    }
    case "number": {
      const n = Number(value);
      if (value.trim() === "" || Number.isNaN(n)) throw new CommandError(`"${name}" must be a number, got "${value}"`);
      return n;
    }
    case "boolean": {
      const lowered = value.toLowerCase();
      if (["true", "1", "yes"].includes(lowered)) return true;
      if (["false", "0", "no"].includes(lowered)) return false;
      throw new CommandError(`"${name}" must be true or false, got "${value}"`);
    }
    case "array":
    case "object":
      try {
        return JSON.parse(value);
      } catch {
        throw new CommandError(`"${name}" must be JSON, got "${value}"`);
      }
    default:
      return value;
  }
}

/** Tool arguments from typed params, checked against the tool's schema. */
export function buildArguments(parsed: ParsedCommand, schema: JsonSchema): Record<string, unknown> {
  const properties = schema.properties ?? {};
  const unknown = Object.keys(parsed.params).filter((k) => !(k in properties));
  if (unknown.length) throw new CommandError(`Unknown param(s): ${unknown.join(", ")}`);
  const missing = (schema.required ?? []).filter((k) => !(k in parsed.params));
  if (missing.length) throw new CommandError(`Missing required param(s): ${missing.join(", ")}`);
  return Object.fromEntries(
    Object.entries(parsed.params).map(([k, v]) => [k, coerce(k, v, properties[k] ?? {})]),
  );
}

function asMarkdown(value: unknown): string {
  const text = JSON.stringify(value);
  return formatToolResult(text) ?? "```json\n" + JSON.stringify(value, null, 2) + "\n```";
}

/** Runs commands; caches the command list and tool schemas per instance
 * (one per logged-in account, see the chat store). */
export class SlashCommandRunner {
  private readonly server = new McpServerClient();
  private commands: Promise<CommandInfo[]> | null = null;
  private tools: Promise<Map<string, ToolInfo>> | null = null;

  /** For the input's suggestions; [] when unavailable. */
  async list(): Promise<CommandInfo[]> {
    this.commands ??= commandsClient.list().catch((err: unknown) => {
      this.commands = null;
      throw err;
    });
    return this.commands;
  }

  private async tool(name: string): Promise<ToolInfo | undefined> {
    this.tools ??= this.server
      .listTools()
      .then((all) => new Map(all.map((t) => [t.name, t])))
      .catch((err: unknown) => {
        this.tools = null;
        throw err;
      });
    return (await this.tools).get(name);
  }

  /** The result as Markdown for the chat. */
  async run(text: string): Promise<string> {
    try {
      if (text.replace(/^\//, "").trim() === "help") return asMarkdown(await commandsClient.helpIndex());
      const parsed = parseCommand(text);
      if (parsed.command === "help") return asMarkdown(await this.help(parsed));

      const commands = await this.list();
      const ofCapability = commands.filter((c) => c.capability === parsed.capability);
      if (ofCapability.length === 0) {
        const known = [...new Set(commands.map((c) => c.capability))].sort().join(", ") || "none";
        throw new CommandError(`Unknown capability "${parsed.capability}". Available: ${known}`);
      }
      const command = ofCapability.find((c) => c.name === parsed.command);
      if (!command) {
        const names = ofCapability.map((c) => c.name).sort().join(", ");
        throw new CommandError(`Unknown command /${parsed.capability} ${parsed.command}. Available: ${names}, help`);
      }
      const tool = await this.tool(command.tool_name);
      if (!tool) throw new CommandError(`Tool ${command.tool_name} is not available right now`);

      const result = await this.server.runTool(tool.name, buildArguments(parsed, tool.inputSchema));
      const shown = formatToolResult(result.text) ?? (result.text || "(no output)");
      return result.isError ? `❌ ${shown}` : shown;
    } catch (err) {
      return `❌ ${err instanceof Error ? err.message : String(err)}`;
    }
  }

  private help(parsed: ParsedCommand): Promise<unknown> {
    const { target = "all", command, ...rest } = parsed.params;
    const extra = Object.keys(rest);
    if (extra.length) throw new CommandError(`Unknown param(s) for help: ${extra.join(", ")}. Use target= or command=.`);
    if (!HELP_TARGETS.includes(target as HelpTarget)) {
      throw new CommandError(`target must be one of ${HELP_TARGETS.join(", ")}`);
    }
    return commandsClient.help(parsed.capability, target as HelpTarget, command);
  }
}
