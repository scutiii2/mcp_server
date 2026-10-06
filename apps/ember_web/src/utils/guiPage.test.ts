import { describe, expect, it, vi } from "vitest";
import type { JsonSchema, ToolRunResult } from "../api/types";
import { applyFieldOverrides, GuiPageError, parseGuiPage, resultValue } from "./guiPage";

const RAW = {
  version: 1,
  title: "Generator",
  description: "d",
  sections: [
    { id: "pw", title: "Password", tool: "tool_a", submit: "Go", fields: [{ param: "length", label: "How long" }],
      result: { kind: "secret", field: "password", detail: "message", refresh_after: "seconds" } },
    { id: "note", text: "Hello" },
  ],
};

describe("parseGuiPage", () => {
  it("accepts a valid page and tags section types", () => {
    const page = parseGuiPage(RAW, ["tool_a"]);
    expect(page.title).toBe("Generator");
    expect(page.sections[0]).toMatchObject({ type: "form", tool: "tool_a", submit: "Go" });
    expect(page.sections[1]).toMatchObject({ type: "text", text: "Hello" });
  });

  it("fills defaults", () => {
    const page = parseGuiPage({ version: 1, title: "T", sections: [{ id: "a", title: "A", tool: "t" }] }, ["t"]);
    expect(page.sections[0]).toMatchObject({ submit: "Run", fields: [], result: { kind: "fields" } });
    expect(page.description).toBe("");
  });

  it("ignores unknown keys with a console warning", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const page = parseGuiPage({ ...RAW, colour: "red" }, ["tool_a"]);
    expect(page.title).toBe("Generator");
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it.each([
    ["wrong version", { ...RAW, version: 2 }],
    ["no sections", { ...RAW, sections: [] }],
    ["not an object", "x"],
    ["bad result kind", { ...RAW, sections: [{ id: "a", title: "A", tool: "tool_a", result: { kind: "bogus" } }] }],
    ["secret without field", { ...RAW, sections: [{ id: "a", title: "A", tool: "tool_a", result: { kind: "secret" } }] }],
    ["duplicate ids", { ...RAW, sections: [{ id: "a", title: "A", tool: "tool_a" }, { id: "a", text: "x" }] }],
  ])("rejects %s", (_name, raw) => {
    expect(() => parseGuiPage(raw, ["tool_a"])).toThrow(GuiPageError);
  });

  it("rejects a tool the capability does not own", () => {
    expect(() => parseGuiPage(RAW, ["tool_b"])).toThrow(/tool_a/);
  });
});

describe("applyFieldOverrides", () => {
  const schema: JsonSchema = {
    type: "object",
    properties: { a: { type: "string" }, b: { type: "string", default: "x" }, c: { type: "string" } },
    required: ["c"],
  };

  it("relabels, reorders and hides optional params", () => {
    const out = applyFieldOverrides(schema, [
      { param: "a", label: "Alpha", order: 2 },
      { param: "b", hidden: true },
      { param: "c", order: 1 },
    ]);
    expect(Object.keys(out.properties!)).toEqual(["c", "a"]);
    expect(out.properties!.a.title).toBe("Alpha");
  });

  it("never hides a required param", () => {
    const out = applyFieldOverrides(schema, [{ param: "c", hidden: true }]);
    expect(Object.keys(out.properties!)).toContain("c");
  });

  it("ignores overrides for params the tool does not have", () => {
    expect(applyFieldOverrides(schema, [{ param: "zzz", label: "x" }])).toEqual(schema);
  });

  it("does not change its input", () => {
    const copy = JSON.parse(JSON.stringify(schema));
    applyFieldOverrides(schema, [{ param: "a", label: "Alpha" }]);
    expect(schema).toEqual(copy);
  });
});

describe("resultValue", () => {
  const ok = (structured?: Record<string, unknown>, text = ""): ToolRunResult => ({ text, isError: false, structured });

  it("reads a structured field", () => {
    expect(resultValue(ok({ code: "123456" }), "code")).toBe("123456");
  });

  it("falls back to the JSON text when there is no structured content", () => {
    expect(resultValue(ok(undefined, '{"code":"654321"}'), "code")).toBe("654321");
  });

  it("is undefined when the field is missing", () => {
    expect(resultValue(ok({ other: 1 }), "code")).toBeUndefined();
    expect(resultValue(ok(undefined, "plain text"), "code")).toBeUndefined();
  });
});
