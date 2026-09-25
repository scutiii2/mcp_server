import type { JsonSchema } from "../api/types";

export type FieldKind = "string" | "number" | "integer" | "boolean" | "enum" | "json";

/** One form field derived from one tool parameter. */
export interface ToolField {
  name: string;
  label: string;
  kind: FieldKind;
  required: boolean;
  description: string;
  options: string[]; // enum choices; empty for other kinds
  /** Initial value in the form's own representation (text for most kinds). */
  initial: string | boolean;
}

/** What the form holds per field: text inputs keep text, checkboxes a boolean. */
export type FieldValues = Record<string, string | boolean>;

/** pydantic writes Optional[X] as anyOf: [X, {type: "null"}]; the form only
 * needs X. Anything with several real alternatives stays as-is (→ json). */
function unwrapOptional(schema: JsonSchema): JsonSchema {
  const alternatives = schema.anyOf ?? schema.oneOf;
  if (!alternatives) return schema;
  const real = alternatives.filter((s) => s.type !== "null");
  if (real.length !== 1) return schema;
  // Keep the outer title/description/default, which pydantic puts there.
  return { ...real[0], title: schema.title, description: schema.description, default: schema.default };
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

function initialFor(kind: FieldKind, value: unknown): string | boolean {
  if (kind === "boolean") return value === true;
  if (value === undefined || value === null) return "";
  if (kind === "json") return JSON.stringify(value, null, 2);
  return String(value);
}

/** Tool input schema to form fields, in the schema's property order. */
export function fieldsFromSchema(schema: JsonSchema): ToolField[] {
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties ?? {}).map(([name, raw]) => {
    const prop = unwrapOptional(raw);
    const kind = kindOf(prop);
    return {
      name,
      label: prop.title ?? name,
      kind,
      required: required.has(name),
      description: prop.description ?? "",
      options: kind === "enum" ? (prop.enum ?? []).map(String) : [],
      initial: initialFor(kind, prop.default),
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
      if (field.required) errors[field.name] = "Required.";
      continue;
    }

    switch (field.kind) {
      case "integer":
      case "number": {
        const n = Number(text);
        if (!Number.isFinite(n)) errors[field.name] = "Must be a number.";
        else if (field.kind === "integer" && !Number.isInteger(n)) errors[field.name] = "Must be a whole number.";
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
        args[field.name] = value;
    }
  }

  return Object.keys(errors).length > 0 ? { ok: false, errors } : { ok: true, args };
}
