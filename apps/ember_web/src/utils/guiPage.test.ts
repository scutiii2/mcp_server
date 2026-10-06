import { describe, expect, it, vi } from "vitest";
import type { JsonSchema, ToolRunResult } from "../api/types";
import { applyFieldOverrides, formSections, GuiPageError, parseGuiPage, resultValue } from "./guiPage";

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

// The generator page in the shape mcp_server's model_dump() produces before
// null-stripping: every unset optional is present as null.
const SERVED_WITH_NULLS = {
  "version": 1,
  "title": "Generator",
  "description": "Random passwords, passphrases, PINs and TOTP codes. Nothing is stored; a value is shown once.",
  "sections": [
    {
      "id": "password",
      "title": "Password",
      "tool": "tool_gen_generatePassword",
      "submit": "Generate",
      "fields": [],
      "result": {
        "kind": "secret",
        "field": "password",
        "detail": "message",
        "refresh_after": null
      }
    },
    {
      "id": "passphrase",
      "title": "Passphrase",
      "tool": "tool_gen_generatePassphrase",
      "submit": "Generate",
      "fields": [],
      "result": {
        "kind": "secret",
        "field": "passphrase",
        "detail": "message",
        "refresh_after": null
      }
    },
    {
      "id": "pin",
      "title": "PIN or one-time code",
      "tool": "tool_gen_generatePin",
      "submit": "Generate",
      "fields": [],
      "result": {
        "kind": "secret",
        "field": "pin",
        "detail": "message",
        "refresh_after": null
      }
    },
    {
      "id": "totp-secret",
      "title": "New TOTP secret",
      "tool": "tool_gen_generateTotpSecret",
      "submit": "Generate",
      "fields": [],
      "result": {
        "kind": "secret",
        "field": "secret",
        "detail": "message",
        "refresh_after": null
      }
    },
    {
      "id": "totp",
      "title": "Current TOTP code",
      "tool": "tool_gen_getTotpCode",
      "submit": "Show code",
      "fields": [],
      "result": {
        "kind": "secret",
        "field": "code",
        "detail": "message",
        "refresh_after": "seconds_remaining"
      }
    },
    {
      "id": "note",
      "title": null,
      "text": "Nothing is stored."
    }
  ]
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
    ["bad section id", { ...RAW, sections: [{ id: "bad id", title: "A", tool: "tool_a" }] }],
    ["empty page title", { ...RAW, title: "" }],
    ["empty form title", { ...RAW, sections: [{ id: "a", title: "", tool: "tool_a" }] }],
    ["empty text", { ...RAW, sections: [{ id: "a", text: "" }] }],
    ...(["field", "detail", "refresh_after"] as const).flatMap((key) =>
      ["a-b", "code\n"].map((bad): [string, unknown] => [
        `${key} '${JSON.stringify(bad).slice(1, -1)}'`,
        { ...RAW, sections: [{ id: "a", title: "A", tool: "tool_a", result: { kind: "secret", field: "x", [key]: bad } }] },
      ]),
    ),
  ])("rejects %s", (_name, raw) => {
    expect(() => parseGuiPage(raw, ["tool_a"])).toThrow(GuiPageError);
  });

  it("accepts the page as mcp_server's model_dump writes it, nulls included", () => {
    const tools = SERVED_WITH_NULLS.sections.flatMap((s) => ("tool" in s && typeof s.tool === "string" ? [s.tool] : []));
    const page = parseGuiPage(SERVED_WITH_NULLS, tools);
    expect(page.sections).toHaveLength(6);
    expect(page.sections[4]).toMatchObject({ type: "form", result: { kind: "secret", field: "code", refresh_after: "seconds_remaining" } });
    expect(page.sections[0]).toMatchObject({ result: { refresh_after: undefined } });
    expect(page.sections[5]).toMatchObject({ type: "text", title: undefined });
  });

  it("treats a section with text as prose and ignores a stray tool", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const page = parseGuiPage({ version: 1, title: "T", sections: [{ id: "n", text: "hi", tool: "tool_zzz" }] }, ["tool_a"]);
    expect(page.sections[0]).toMatchObject({ type: "text", text: "hi" });
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("rejects a tool the capability does not own", () => {
    expect(() => parseGuiPage(RAW, ["tool_b"])).toThrow(/tool_a/);
  });

  const TABS = {
    id: "gen",
    tabs: [
      { id: "a", title: "A", tool: "tool_a", live: true, result: { kind: "secret", field: "v", strength: "bits", group: 3 } },
      { id: "b", title: "B", tool: "tool_a" },
    ],
  };
  const tabsPage = (section: unknown) => ({ version: 1, title: "T", sections: [section] });

  it("accepts a tabs section and tags it", () => {
    const page = parseGuiPage(tabsPage(TABS), ["tool_a"]);
    const section = page.sections[0]!;
    expect(section).toMatchObject({ type: "tabs", id: "gen" });
    if (section.type !== "tabs") throw new Error("not tabs");
    expect(section.tabs[0]).toMatchObject({ type: "form", live: true, result: { strength: "bits", group: 3 } });
    expect(section.tabs[1]).toMatchObject({ live: false });
  });

  it("accepts null strength and group, as an unstripped page would carry them", () => {
    const page = parseGuiPage(
      tabsPage({ ...TABS, tabs: [{ id: "a", title: "A", tool: "tool_a", live: false, result: { kind: "secret", field: "v", strength: null, group: null } }, TABS.tabs[1]] }),
      ["tool_a"],
    );
    expect(page.sections[0]).toMatchObject({ type: "tabs" });
  });

  it("formSections lists the forms inside tabs too, in order", () => {
    const page = parseGuiPage(
      { version: 1, title: "T", sections: [{ id: "top", title: "Top", tool: "tool_a" }, TABS, { id: "n", text: "x" }] },
      ["tool_a"],
    );
    expect(formSections(page.sections).map((f) => f.id)).toEqual(["top", "a", "b"]);
  });

  it.each([
    ["one tab", tabsPage({ ...TABS, tabs: TABS.tabs.slice(0, 1) })],
    ["nine tabs", tabsPage({ ...TABS, tabs: Array.from({ length: 9 }, (_, i) => ({ id: `t${i}`, title: "T", tool: "tool_a" })) })],
    ["tabs not a list", tabsPage({ ...TABS, tabs: "x" })],
    ["a text section as a tab", tabsPage({ ...TABS, tabs: [TABS.tabs[0], { id: "x", text: "not a form" }] })],
    ["a tab id repeated", tabsPage({ ...TABS, tabs: [TABS.tabs[0], { id: "a", title: "Again", tool: "tool_a" }] })],
    ["a tab id equal to a section id", { version: 1, title: "T", sections: [{ id: "a", title: "Top", tool: "tool_a" }, TABS] }],
    ["a foreign tool in a tab", tabsPage({ ...TABS, tabs: [TABS.tabs[0], { id: "b", title: "B", tool: "elsewhere" }] })],
    ["strength on a message", tabsPage({ ...TABS, tabs: [{ id: "a", title: "A", tool: "tool_a", result: { kind: "message", strength: "bits" } }, TABS.tabs[1]] })],
    ["group on a table", tabsPage({ ...TABS, tabs: [{ id: "a", title: "A", tool: "tool_a", result: { kind: "table", field: "rows", group: 3 } }, TABS.tabs[1]] })],
    ...[1, 9, 2.5, "3"].map((group): [string, unknown] => [
      `group ${JSON.stringify(group)}`,
      tabsPage({ ...TABS, tabs: [{ id: "a", title: "A", tool: "tool_a", result: { kind: "secret", field: "v", group } }, TABS.tabs[1]] }),
    ]),
    ["strength not an identifier", tabsPage({ ...TABS, tabs: [{ id: "a", title: "A", tool: "tool_a", result: { kind: "secret", field: "v", strength: "a-b" } }, TABS.tabs[1]] })],
  ])("rejects %s", (_name, raw) => {
    expect(() => parseGuiPage(raw, ["tool_a"])).toThrow(GuiPageError);
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
