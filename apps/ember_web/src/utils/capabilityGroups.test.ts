import { describe, expect, it } from "vitest";
import type { CapabilityInfo } from "../api/CommandsClient";
import type { ToolInfo } from "../api/types";
import { groupTools } from "./capabilityGroups";

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

  it("treats a blank query as no filter", () => {
    expect(groupTools(CAPS, TOOLS, "   ").groups).toHaveLength(3);
  });
});
