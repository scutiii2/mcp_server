import type { JsonSchema } from "../api/types";

/** How a value is parsed into a tool argument. */
export type FieldKind = "string" | "number" | "integer" | "boolean" | "enum" | "json";

/** How a field is drawn. A tool can ask for one with a schema hint
 * (`input`, chat_app's command-form convention); otherwise it follows the
 * kind. "select" with an `optionsUrl` gets its options from mcp_server; a
 * "file" field uploads the dropped file and holds its server-side path. */
export type FieldWidget =
  | "text"
  | "textarea"
  | "password"
  | "number"
  | "range"
  | "date"
  | "select"
  | "checkbox"
  | "json"
  | "file";

const WIDGETS = new Set<FieldWidget>(["text", "textarea", "password", "number", "range", "date", "select", "checkbox", "json", "file"]);

/** One form field derived from one tool parameter. */
export interface ToolField {
  name: string;
  label: string;
  kind: FieldKind;
  widget: FieldWidget;
  required: boolean;
  description: string;
  options: string[]; // enum choices; empty for other kinds
  /** Suggested values (the schema's `examples`), offered while typing. */
  examples: string[];
  /** Initial value in the form's own representation (text for most kinds). */
  initial: string | boolean;
  /** A path on mcp_server listing this select's options; may contain
   * {param} placeholders filled from `dependsOn`. */
  optionsUrl?: string;
  dependsOn?: string;
  /** On choosing an option: {other param: option field} to fill in. */
  sets: Record<string, string>;
  /** On choosing an option: {label: option field} shown read-only. */
  shows: Record<string, string>;
  min?: number;
  max?: number;
  step?: number;
  maxLength?: number;
  pattern?: string;
}

/** What the form holds per field: text inputs keep text, checkboxes a boolean. */
export type FieldValues = Record<string, string | boolean>;

/** pydantic writes Optional[X] as anyOf: [X, {type: "null"}]; the form only
 * needs X. Anything with several real alternatives stays as-is (→ json).
 * Hints pydantic puts next to the anyOf are kept. */
function unwrapOptional(schema: JsonSchema): JsonSchema {
  const alternatives = schema.anyOf ?? schema.oneOf;
  if (!alternatives) return schema;
  const real = alternatives.filter((s) => s.type !== "null");
  if (real.length !== 1) return schema;
  const { anyOf: _anyOf, oneOf: _oneOf, ...outer } = schema;
  return { ...real[0], ...outer };
}

function kindOf(schema: JsonSchema): FieldKind {
  if (schema.enum && schema.enum.length > 0) return "enum";
  const type = Array.isArray(schema.type) ? schema.type.find((t) => t !== "null") : schema.type;
  switch (type) {
    case "string":
      return "string";
    case "number":
      return "number";
    case "integer":
      return "integer";
    case "boolean":
      return "boolean";
    default:
      return "json"; // object, array, or anything the form has no widget for
  }
}

function widgetOf(kind: FieldKind, schema: JsonSchema): FieldWidget {
  if (schema.format === "file") return "file";
  if (kind === "boolean") return "checkbox";
  if (schema.input && WIDGETS.has(schema.input as FieldWidget)) return schema.input as FieldWidget;
  if (kind === "enum" || schema.options_url) return "select";
  if (kind === "json") return "json";
  if (kind === "number" || kind === "integer") return "number";
  if (schema.format === "date") return "date";
  if (schema.format === "password") return "password";
  return "text";
}

/** "{timestamp}" in an `initial` hint: the current local time, as chat_app fills it. */
function expandInitial(template: string): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return template.replaceAll("{timestamp}", stamp);
}

function initialFor(kind: FieldKind, schema: JsonSchema): string | boolean {
  if (kind === "boolean") return schema.default === true;
  if (typeof schema.initial === "string" && schema.default === undefined) return expandInitial(schema.initial);
  const value = schema.default;
  if (value === undefined || value === null) return "";
  if (kind === "json") return JSON.stringify(value, null, 2);
  return String(value);
}

function stringMap(value: unknown): Record<string, string> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value).filter((e): e is [string, string] => typeof e[1] === "string"));
}

/** Tool input schema to form fields, in the schema's property order. */
export function fieldsFromSchema(schema: JsonSchema): ToolField[] {
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties ?? {}).map(([name, raw]) => {
    const prop = unwrapOptional(raw);
    const kind = kindOf(prop);
    const widget = widgetOf(kind, prop);
    return {
      name,
      label: prop.title ?? name,
      kind,
      widget,
      required: required.has(name),
      description: prop.description ?? "",
      options: kind === "enum" ? (prop.enum ?? []).map(String) : [],
      examples: (prop.examples ?? []).filter((e) => e !== null && typeof e !== "object").map(String),
      initial: initialFor(kind, prop),
      optionsUrl: typeof prop.options_url === "string" ? prop.options_url : undefined,
      dependsOn: typeof prop.depends_on === "string" ? prop.depends_on : undefined,
      sets: stringMap(prop.sets),
      shows: stringMap(prop.shows),
      min: prop.minimum,
      max: prop.maximum,
      step: typeof prop.step === "number" ? prop.step : undefined,
      maxLength: prop.maxLength,
      pattern: prop.pattern,
    };
  });
}

export function initialValues(fields: ToolField[]): FieldValues {
  return Object.fromEntries(fields.map((f) => [f.name, f.initial]));
}

export type BuildResult =
  | { ok: true; args: Record<string, unknown> }
  | { ok: false; errors: Record<string, string> };

/** Form values to tool arguments. Empty optional fields are left out so the
 * tool's own default applies; every problem is reported per field. */
export function buildArgs(fields: ToolField[], values: FieldValues): BuildResult {
  const args: Record<string, unknown> = {};
  const errors: Record<string, string> = {};

  for (const field of fields) {
    const value = values[field.name];

    if (field.kind === "boolean") {
      args[field.name] = value === true;
      continue;
    }

    const text = typeof value === "string" ? value.trim() : "";
    if (text === "") {
      if (field.required) errors[field.name] = field.widget === "file" ? "Choose a file." : "Required.";
      continue;
    }

    switch (field.kind) {
      case "integer":
      case "number": {
        const n = Number(text);
        if (!Number.isFinite(n)) errors[field.name] = "Must be a number.";
        else if (field.kind === "integer" && !Number.isInteger(n)) errors[field.name] = "Must be a whole number.";
        else if (field.min !== undefined && n < field.min) errors[field.name] = `Must be at least ${field.min}.`;
        else if (field.max !== undefined && n > field.max) errors[field.name] = `Must be at most ${field.max}.`;
        else args[field.name] = n;
        break;
      }
      case "json":
        try {
          args[field.name] = JSON.parse(text);
        } catch {
          errors[field.name] = "Must be valid JSON.";
        }
        break;
      default: // string, enum - sent as typed; trimming was only for the empty check
        if (field.maxLength !== undefined && String(value).length > field.maxLength) {
          errors[field.name] = `At most ${field.maxLength} characters.`;
        } else if (field.pattern && !new RegExp(field.pattern, "u").test(String(value))) {
          errors[field.name] = "Doesn't have the expected format.";
        } else {
          args[field.name] = value;
        }
    }
  }

  return Object.keys(errors).length > 0 ? { ok: false, errors } : { ok: true, args };
}

/** Quotes a value so "/cap cmd key=value" parsing (splitWords) keeps it
 * one word: spaces, quotes and backslashes (Windows paths) survive. */
export function quoteWord(value: string): string {
  if (value !== "" && !/[\s"'\\]/.test(value)) return value;
  return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

/** Tool arguments as the "/<capability> <command> key=value ..." text a
 * user could have typed. */
export function commandText(capability: string, command: string, args: Record<string, unknown>): string {
  const params = Object.entries(args).map(([key, value]) => {
    const text = typeof value === "string" ? value : typeof value === "object" ? JSON.stringify(value) : String(value);
    return `${key}=${quoteWord(text)}`;
  });
  return [`/${capability}`, command, ...params].join(" ");
}
