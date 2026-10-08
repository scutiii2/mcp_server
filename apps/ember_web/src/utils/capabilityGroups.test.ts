import { describe, expect, it } from "vitest";
import type { CapabilityInfo } from "../api/CommandsClient";
import type { ExtensionInfo } from "../api/ExtensionsClient";
import type { ToolInfo } from "../api/types";
import { addedOnly, groupTools } from "./capabilityGroups";

const cap = (name: string, tools: string[], extra: Partial<CapabilityInfo> = {}): CapabilityInfo => ({
  name,
  enabled: true,
  label: null,
  tools,
  resources: [],
  ...extra,
});

const tool = (name: string, title = name, description = ""): ToolInfo => ({
  name,
  title,
  description,
  inputSchema: { type: "object", properties: {} },
});

const CAPS = [
  cap("pdf", ["tool_pdf_merge", "tool_pdf_split"], { label: "PDF files" }),
  cap("services", ["tool_srv_restart"]),
  cap("off", [], { enabled: false }),
];
const TOOLS = [
  tool("tool_pdf_merge", "Merge", "Join PDFs"),
  tool("tool_pdf_split", "Split"),
  tool("tool_srv_restart", "Restart Service"),
  tool("ext__echo", "Echo", "from an extension"),
];

const names = (tools: ToolInfo[]) => tools.map((t) => t.name);

describe("groupTools", () => {
  it("puts each tool under the capability that lists it", () => {
    const { groups, otherTools } = groupTools(CAPS, TOOLS, "");

    expect(groups.map((g) => g.capability.name)).toEqual(["pdf", "services", "off"]);
    expect(names(groups[0]!.tools)).toEqual(["tool_pdf_merge", "tool_pdf_split"]);
    expect(names(groups[1]!.tools)).toEqual(["tool_srv_restart"]);
    expect(groups[2]!.tools).toEqual([]);
    expect(names(otherTools)).toEqual(["ext__echo"]);
  });

  it("keeps a capability's listed order, not the order the server returned the tools in", () => {
    const { groups } = groupTools(CAPS, [...TOOLS].reverse(), "");

    expect(names(groups[0]!.tools)).toEqual(["tool_pdf_merge", "tool_pdf_split"]);
  });

  it("ignores a listed tool the server did not return", () => {
    const { groups } = groupTools([cap("pdf", ["tool_pdf_merge", "gone"])], TOOLS, "");

    expect(names(groups[0]!.tools)).toEqual(["tool_pdf_merge"]);
  });

  it("filters by title, name and description, case-insensitively, hiding empty groups", () => {
    expect(groupTools(CAPS, TOOLS, "JOIN").groups.map((g) => g.capability.name)).toEqual(["pdf"]);
    expect(names(groupTools(CAPS, TOOLS, "JOIN").groups[0]!.tools)).toEqual(["tool_pdf_merge"]);
    expect(names(groupTools(CAPS, TOOLS, "srv").groups[0]!.tools)).toEqual(["tool_srv_restart"]);
    expect(groupTools(CAPS, TOOLS, "nothing like it").groups).toEqual([]);
  });

  it("shows every tool of a capability whose own name or label matches", () => {
    const { groups } = groupTools(CAPS, TOOLS, "pdf files");

    expect(groups.map((g) => g.capability.name)).toEqual(["pdf"]);
    expect(names(groups[0]!.tools)).toEqual(["tool_pdf_merge", "tool_pdf_split"]);
  });

  it("filters the tools no capability claims too", () => {
    expect(names(groupTools(CAPS, TOOLS, "extension").otherTools)).toEqual(["ext__echo"]);
    expect(groupTools(CAPS, TOOLS, "merge").otherTools).toEqual([]);
  });

  describe("with extensions", () => {
    const ext = (id: string, tools: string[], extra: Partial<ExtensionInfo> = {}): ExtensionInfo => ({
      id,
      label: id.toUpperCase(),
      description: "",
      status: "connected",
      error: null,
      tools,
      ...extra,
    });
    const EXTS = [ext("ext", ["ext__echo"]), ext("down", [], { status: "error", error: "refused" })];

    it("moves an extension's tools out of 'other' into its own group", () => {
      const { extensionGroups, otherTools } = groupTools(CAPS, [...TOOLS, tool("stray")], "", EXTS);

      expect(extensionGroups.map((g) => g.extension.id)).toEqual(["ext", "down"]);
      expect(names(extensionGroups[0]!.tools)).toEqual(["ext__echo"]);
      expect(extensionGroups[1]!.tools).toEqual([]);
      expect(names(otherTools)).toEqual(["stray"]);
    });

    it("finds a tool by the extension's namespace even if its tool list lacks it", () => {
      const { extensionGroups } = groupTools([], TOOLS, "", [ext("ext", [])]);

      expect(names(extensionGroups[0]!.tools)).toEqual(["ext__echo"]);
    });

    it("never takes a tool a capability already lists", () => {
      const { groups, extensionGroups } = groupTools(CAPS, TOOLS, "", [ext("tool", ["tool_pdf_merge"])]);

      expect(names(groups[0]!.tools)).toEqual(["tool_pdf_merge", "tool_pdf_split"]);
      expect(extensionGroups[0]!.tools).toEqual([]);
    });

    it("filters extensions like capabilities", () => {
      expect(groupTools(CAPS, TOOLS, "echo", EXTS).extensionGroups.map((g) => g.extension.id)).toEqual(["ext"]);
      expect(groupTools(CAPS, TOOLS, "DOWN", EXTS).extensionGroups.map((g) => g.extension.id)).toEqual(["down"]);
      expect(groupTools(CAPS, TOOLS, "merge", EXTS).extensionGroups).toEqual([]);
    });
  });

  it("treats a blank query as no filter", () => {
    expect(groupTools(CAPS, TOOLS, "   ").groups).toHaveLength(3);
  });
});

describe("addedOnly", () => {
  const caps = [
    { name: "pdf", enabled: true, label: "PDF files", tools: ["tool_pdf_merge"], resources: [] },
    { name: "calc", enabled: true, label: "Calculator", tools: ["tool_calc"], resources: [] },
  ];
  const exts = [
    { id: "notes", label: "Notes", description: "", status: "connected", error: null, tools: ["notes__add"] },
    { id: "wiki", label: "Wiki", description: "", status: "connected", error: null, tools: [] },
  ];
  const all = [tool("tool_pdf_merge", "Merge"), tool("tool_calc", "Calc"), tool("notes__add", "Add"), tool("wiki__find", "Find"), tool("stray", "Stray")];

  it("keeps only the added capabilities and extensions", () => {
    const out = addedOnly(caps, exts, all, ["pdf"], ["notes"]);

    expect(out.capabilities.map((c) => c.name)).toEqual(["pdf"]);
    expect(out.extensions.map((e) => e.id)).toEqual(["notes"]);
  });

  it("drops the tools of what is not added so they do not show up as other tools", () => {
    const out = addedOnly(caps, exts, all, ["pdf"], ["notes"]);

    expect(out.tools.map((t) => t.name)).toEqual(["tool_pdf_merge", "notes__add", "stray"]);
  });

  it("drops an extension's tools found by its namespace too", () => {
    expect(addedOnly(caps, exts, all, [], []).tools.map((t) => t.name)).toEqual(["stray"]);
  });

  it("ignores added ids that no longer exist", () => {
    expect(addedOnly(caps, exts, all, ["gone"], ["gone"]).capabilities).toEqual([]);
  });
});
