/** One tool an answer ran, as ember_api saves it on the answer. */
export interface ToolStep {
  /** Live steps only: the step's id in the event stream. */
  id?: string;
  /** Which agent ran it, when a delegated agent did (absent for the main agent's own steps and older answers). */
  agent_id?: string;
  agent_label?: string;
  tool: string;
  /** Readable title from ai_agent, if it gave one. */
  label: string;
  arguments: Record<string, unknown>;
  /** null: still running, or the answer stopped before it finished. */
  ok: boolean | null;
  /** The result text, cut to 4,000 characters. */
  result: string;
}

/** An agent that is working on the running answer right now (ember_api's `active_agents`). */
export interface ActiveAgent {
  agent_id: string;
  label: string;
  /** When it started (ISO-8601 UTC). */
  since: string;
  /** The orchestrator's delegate_to_agent step that handed it its question. */
  step_id: string;
}

/** One message of a chat, as ember_api stores it. */
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  /** summary: what the agent remembers of earlier messages; log_attachment:
   * the raw messages a summary or clear replaced (never sent to the agent);
   * command: a slash command and its result. */
  kind?: "summary" | "log_attachment" | "command";
  /** When it was written: ISO 8601 UTC (messages saved before this existed lack it). */
  at?: string;
  /** Id of the ember agent that wrote this answer (answers from before this was saved lack it). */
  agent?: string;
  model?: string;
  total_tokens?: number;
  /** The split of total_tokens (answers from before these were saved lack them). */
  input_tokens?: number;
  output_tokens?: number;
  /** How long the whole turn took, in seconds. */
  duration_s?: number;
  /** How full the agent's context was after this answer. */
  context_tokens?: number;
  context_window?: number;
  /** The tools this answer ran. */
  steps?: ToolStep[];
  /** Who used the tokens, when the answer ran several agents (its own plus
   * delegated ones); absent when only one did. */
  agent_usage?: AgentUsage[];
}

/** One agent's share of an answer that ran several. */
export interface AgentUsage {
  /** The agent's id (older answers: its provider's name). */
  agent: string;
  /** Display name; absent on older answers. */
  agent_label?: string;
  provider_id?: string;
  /** Absent: the provider was used directly. */
  gateway?: string;
  /** The agent that handed this one its work, when it was delegated. */
  delegated_by?: string;
  model?: string;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens: number;
  /** When the agent's call began and ended (ISO-8601 UTC; no zone means UTC). */
  started_at?: string;
  finished_at?: string;
}

/** A tool run that waits for the user's answer before it starts. */
export interface PendingApproval {
  /** The step's id: what an answer names. */
  id: string;
  tool: string;
  label: string;
  arguments: Record<string, unknown>;
}

/** The user's answer to a PendingApproval: run it this once, run it and stop
 * asking about this tool in this chat, or don't run it. */
export type ApprovalDecision = "allow" | "always" | "deny";

/** One choice of a question the agent asks. */
export interface QuestionOption {
  label: string;
  description?: string;
}

/** One question the agent asks. The page always adds an "Other" typed answer. */
export interface Question {
  /** A very short label (a chip). */
  header: string;
  question: string;
  multi_select: boolean;
  options: QuestionOption[];
}

/** Questions that wait for the user's answer before the agent goes on. */
export interface PendingQuestion {
  /** The step's id: what an answer names. */
  id: string;
  questions: Question[];
}

/** The answer to one question: the labels chosen and/or the user's own words. */
export interface QuestionAnswer {
  selected: string[];
  other: string | null;
}

/** A private extension a turn could not use, and why. */
export interface TurnNotice {
  id: string;
  label: string;
  error: string;
}

/** Events of a turn ember_api runs, as its /events stream sends them. The
 * token/step ones are ai_agent's own, relayed. */
export interface TurnPlan {
  agent_id?: string;
  agent_label?: string;
  items: { text: string; status: "pending" | "in_progress" | "done" }[];
}

export type TurnEvent = { sequence: number } & (
  | { type: "snapshot"; text: string; activity: string; steps?: ToolStep[]; approvals?: PendingApproval[]; questions?: PendingQuestion[]; active_agents?: ActiveAgent[]; plans?: TurnPlan[] }
  | ({ type: "plan_update" } & TurnPlan)
  | { type: "token"; text: string }
  | { type: "token_reset" }
  | { type: "step_start"; id: string; tool: string; label?: string; arguments: unknown; agent_id?: string; agent_label?: string }
  | { type: "step_progress"; id: string; message: string; agent_id?: string; agent_label?: string }
  | { type: "step_end"; id: string; ok: boolean; result: string; agent_id?: string; agent_label?: string }
  | { type: "approval_request"; id: string; tool: string; label?: string; arguments: unknown }
  | { type: "approval_resolved"; id: string; outcome: string }
  | { type: "question_request"; id: string; questions: Question[] }
  | { type: "question_resolved"; id: string; outcome: string }
  | { type: "notice"; notices: TurnNotice[] }
  | { type: "usage"; total_tokens: number; estimated: boolean }
  | { type: "summarizing" }
  | { type: "summarized" }
  | { type: "cancelling" }
  | { type: "agent_start"; agent_id: string; agent_label: string; delegated_by: string; question: string; step_id: string; at: string }
  | { type: "agent_end"; agent_id: string; agent_label: string; ok: boolean; step_id: string; at: string }
  | { type: "agent_token"; agent_id: string; agent_label: string; step_id: string; text: string; reset?: boolean }
  | { type: "final"; message: ChatMessage; cancelled: boolean }
  | { type: "error"; message: string }
);

/** One mcp_server resource, or a URI template (with {placeholders}). */
export interface ResourceInfo {
  uri: string;
  name: string;
  description: string;
  template: boolean;
}

/** One mcp_server tool as the Tools page lists it. */
export interface ToolInfo {
  name: string;
  /** Display title: the server's own title if it gives one, else derived from the name. */
  title: string;
  description: string;
  /** The tool's parameters as JSON Schema (pydantic-generated by FastMCP). */
  inputSchema: JsonSchema;
}

/** The subset of JSON Schema that tool parameter forms read. */
export interface JsonSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  oneOf?: JsonSchema[];
  format?: string;
  examples?: unknown[];
  minimum?: number;
  maximum?: number;
  maxLength?: number;
  pattern?: string;
  // Form hints a tool adds with Field(json_schema_extra=...), as chat_app's
  // command form reads them.
  /** Widget: text, textarea, password, number, range, date, select, checkbox, file. */
  input?: string;
  /** A path on mcp_server listing a select's options. */
  options_url?: string;
  /** The param whose value fills options_url's {placeholder}. */
  depends_on?: string;
  /** {param: option field}: filled in when an option is chosen. */
  sets?: Record<string, string>;
  /** {label: option field}: shown when an option is chosen. */
  shows?: Record<string, string>;
  /** Prefilled text; "{timestamp}" becomes the current time. */
  initial?: string;
  step?: number;
}

/** One mcp_server tool call's outcome as the Tools page shows it. */
export interface ToolRunResult {
  /** All text content parts, joined. */
  text: string;
  /** The tool reported failure (MCP isError), as opposed to a transport error. */
  isError: boolean;
  structured?: Record<string, unknown>;
}

/** One saved chat: its turns plus sidebar metadata. Times are epoch ms. */
export interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
  /** ai_agent id this chat last talked to; absent on chats saved before it existed. */
  agentId?: string;
  /** False until the transcript is fetched (the list comes without it). */
  messagesLoaded?: boolean;
  /** From the server's list, for chats whose messages aren't loaded yet. */
  messageCount?: number;
  /** ember_api is writing an answer for it right now. */
  running?: boolean;
  /** The folder it is filed in (ember_api's id), or none. */
  folderId?: number | null;
  /** Shown in the Pinned section, above the folders. */
  pinned?: boolean;
  createdAt: number;
  updatedAt: number;
}

/** The main agent, as ember_api's GET /api/agent returns it. No URL: the
 * browser only reaches agents through ember_api's proxy. */
export interface AgentInfo {
  id: string;
  label: string;
}
