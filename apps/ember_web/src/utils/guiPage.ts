import type {
  GuiFieldSpec,
  GuiFormSectionSpec,
  GuiPageSpec,
  GuiResultKind,
  GuiResultSpec,
  GuiTextSectionSpec,
} from "../api/CapabilityPagesClient";
import type { JsonSchema, ToolRunResult } from "../api/types";

/** The page's layout is unusable; the message is safe to show. */
export class GuiPageError extends Error {}

const KINDS: GuiResultKind[] = ["secret", "message", "table", "fields"];
const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;
const SECTION_ID = /^[A-Za-z0-9_-]{1,64}$/;

type Obj = Record<string, unknown>;

function isObj(value: unknown): value is Obj {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function warnUnknown(where: string, obj: Obj, known: string[]): void {
  const extra = Object.keys(obj).filter((k) => !known.includes(k));
  if (extra.length) console.warn(`Capability page: ignoring unknown ${where} keys: ${extra.join(", ")}`);
}

function text(obj: Obj, key: string, where: string, required = true): string | undefined {
  const value = obj[key];
  if (value == null && !required) return undefined;
  if (typeof value !== "string" || value === "") throw new GuiPageError(`${where}: '${key}' must be a non-empty string`);
  return value;
}

function name(obj: Obj, key: string, where: string): string | undefined {
  const value = text(obj, key, where, false);
  if (value !== undefined && !IDENTIFIER.test(value)) throw new GuiPageError(`${where}: '${key}' is not a field name`);
  return value;
}

function parseResult(raw: unknown, where: string): GuiResultSpec {
  if (raw === undefined) return { kind: "fields" };
  if (!isObj(raw)) throw new GuiPageError(`${where}: 'result' must be an object`);
  warnUnknown(`${where} result`, raw, ["kind", "field", "detail", "refresh_after"]);
  const kind = (raw.kind ?? "fields") as GuiResultKind;
  if (!KINDS.includes(kind)) throw new GuiPageError(`${where}: unknown result kind '${String(raw.kind)}'`);
  const result: GuiResultSpec = {
    kind,
    field: name(raw, "field", where),
    detail: name(raw, "detail", where),
    refresh_after: name(raw, "refresh_after", where),
  };
  if ((kind === "secret" || kind === "table") && !result.field) {
    throw new GuiPageError(`${where}: result kind '${kind}' needs a 'field'`);
  }
  return result;
}

function parseFields(raw: unknown, where: string): GuiFieldSpec[] {
  if (raw === undefined) return [];
  if (!Array.isArray(raw)) throw new GuiPageError(`${where}: 'fields' must be a list`);
  return raw.map((item) => {
    if (!isObj(item) || typeof item.param !== "string") throw new GuiPageError(`${where}: each field needs a 'param'`);
    warnUnknown(`${where} field`, item, ["param", "label", "order", "hidden"]);
    return {
      param: item.param,
      label: typeof item.label === "string" ? item.label : undefined,
      order: typeof item.order === "number" ? item.order : undefined,
      hidden: item.hidden === true,
    };
  });
}

function parseSection(raw: unknown, index: number): GuiFormSectionSpec | GuiTextSectionSpec {
  const where = `section ${index + 1}`;
  if (!isObj(raw)) throw new GuiPageError(`${where} must be an object`);
  const id = text(raw, "id", where)!;
  if (!SECTION_ID.test(id)) throw new GuiPageError(`${where}: bad id '${id}'`);
  // Any section with a `text` key is prose (as mcp_server reads it), even if it also names a tool.
  if ("text" in raw) {
    warnUnknown(where, raw, ["id", "title", "text"]);
    return { type: "text", id, title: text(raw, "title", where, false), text: text(raw, "text", where)! };
  }
  warnUnknown(where, raw, ["id", "title", "tool", "submit", "fields", "result"]);
  return {
    type: "form",
    id,
    title: text(raw, "title", where)!,
    tool: text(raw, "tool", where)!,
    submit: text(raw, "submit", where, false) ?? "Run",
    fields: parseFields(raw.fields, where),
    result: parseResult(raw.result, where),
  };
}

/** Checks a page from mcp_server before anything is drawn. Every tool a page
 * names must be one of `ownTools` (its own capability's); unknown keys are
 * ignored with a console warning so a newer page still opens. */
export function parseGuiPage(raw: unknown, ownTools: string[]): GuiPageSpec {
  if (!isObj(raw)) throw new GuiPageError("The page is not an object");
  warnUnknown("page", raw, ["version", "title", "description", "sections"]);
  if (raw.version !== 1) throw new GuiPageError(`Unsupported page version ${String(raw.version)}`);
  if (!Array.isArray(raw.sections) || raw.sections.length === 0) throw new GuiPageError("The page has no sections");
  const sections = raw.sections.map(parseSection);
  const ids = sections.map((s) => s.id);
  const dup = ids.find((id, i) => ids.indexOf(id) !== i);
  if (dup) throw new GuiPageError(`Duplicate section id '${dup}'`);
  const foreign = sections.flatMap((s) => (s.type === "form" && !ownTools.includes(s.tool) ? [s.tool] : []));
  if (foreign.length) throw new GuiPageError(`The page names tools its capability does not own: ${foreign.join(", ")}`);
  return {
    version: 1,
    title: text(raw, "title", "page")!,
    description: typeof raw.description === "string" ? raw.description : "",
    sections,
  };
}

/** The tool's schema with the page's label/order/hidden overrides applied.
 * A required param is never hidden. Does not change its input. */
export function applyFieldOverrides(schema: JsonSchema, fields: GuiFieldSpec[]): JsonSchema {
  const properties = schema.properties ?? {};
  const required = new Set(schema.required ?? []);
  const byParam = new Map(fields.map((f) => [f.param, f]));
  const entries = Object.entries(properties)
    .filter(([param]) => !(byParam.get(param)?.hidden && !required.has(param)))
    .map(([param, prop]): [string, JsonSchema] => {
      const label = byParam.get(param)?.label;
      return [param, label ? { ...prop, title: label } : prop];
    });
  const rank = (param: string): number => byParam.get(param)?.order ?? Number.MAX_SAFE_INTEGER;
  // Array.sort is stable, so params without an order keep the tool's own order.
  entries.sort((x, y) => rank(x[0]) - rank(y[0]));
  return { ...schema, properties: Object.fromEntries(entries) };
}

/** One value from a tool's result: its structured content, or the JSON in its text. */
export function resultValue(result: ToolRunResult, field: string): unknown {
  if (result.structured && field in result.structured) return result.structured[field];
  try {
    const parsed: unknown = JSON.parse(result.text);
    return isObj(parsed) ? parsed[field] : undefined;
  } catch {
    return undefined;
  }
}
