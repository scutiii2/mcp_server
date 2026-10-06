import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { GuiFormSectionSpec, GuiTabsSectionSpec } from "../api/CapabilityPagesClient";
import type { ToolInfo, ToolRunResult } from "../api/types";
import GuiTabsSection from "./GuiTabsSection.vue";

vi.mock("../api/CommandsClient", () => ({ commandsClient: { options: vi.fn(), upload: vi.fn() } }));

const tool = (name: string): ToolInfo => ({
  name,
  title: name,
  description: "",
  inputSchema: { type: "object", properties: { n: { type: "integer", default: 1 } } },
});
const TOOLS = { tool_a: tool("tool_a"), tool_b: tool("tool_b") };
const form = (id: string, title: string, toolName: string, live = false): GuiFormSectionSpec => ({
  type: "form",
  id,
  title,
  tool: toolName,
  submit: "Go",
  fields: [],
  live,
  result: { kind: "secret", field: "v" },
});
const SECTION: GuiTabsSectionSpec = {
  type: "tabs",
  id: "gen",
  tabs: [form("a", "Alpha", "tool_a", true), form("b", "Beta", "tool_b")],
};
const ok = (v: string): ToolRunResult => ({ text: "", isError: false, structured: { v } });

function mountTabs(runTool = vi.fn().mockImplementation(async (name: string) => ok(name))) {
  return { runTool, w: mount(GuiTabsSection, { props: { section: SECTION, tools: TOOLS, runTool } }) };
}

describe("GuiTabsSection", () => {
  it("shows every tab title and only the first tab's panel", async () => {
    const { w, runTool } = mountTabs();
    await flushPromises();
    expect(w.findAll("[data-test=tab]").map((t) => t.text())).toEqual(["Alpha", "Beta"]);
    expect(w.findAll("[data-test=tab]").map((t) => t.attributes("aria-selected"))).toEqual(["true", "false"]);
    expect(runTool).toHaveBeenCalledTimes(1); // Alpha is live: it ran, Beta did not
    expect(runTool).toHaveBeenCalledWith("tool_a", { n: 1 });
    expect(w.get("[data-test=secret]").text()).toBe("tool_a");
  });

  it("switches tabs by click and does not run a tab that is not live", async () => {
    const { w, runTool } = mountTabs();
    await flushPromises();
    await w.findAll("[data-test=tab]")[1]!.trigger("click");
    await flushPromises();
    expect(w.findAll("[data-test=tab]")[1]!.attributes("aria-selected")).toBe("true");
    expect(runTool).toHaveBeenCalledTimes(1);
    expect(w.find("button.run").exists()).toBe(true);
  });

  it("keeps a tab's settings and result when you come back", async () => {
    const { w, runTool } = mountTabs();
    await flushPromises();
    await w.findAll("[data-test=tab]")[1]!.trigger("click");
    await w.findAll("[data-test=tab]")[0]!.trigger("click");
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(1); // coming back does not regenerate
    expect(w.get("[data-test=secret]").text()).toBe("tool_a");
  });

  it("moves with the arrow keys, Home and End, wrapping around", async () => {
    const { w } = mountTabs();
    await flushPromises();
    const list = w.get("[role=tablist]");
    await list.trigger("keydown", { key: "ArrowRight" });
    expect(w.findAll("[data-test=tab]")[1]!.attributes("aria-selected")).toBe("true");
    await list.trigger("keydown", { key: "ArrowRight" });
    expect(w.findAll("[data-test=tab]")[0]!.attributes("aria-selected")).toBe("true");
    await list.trigger("keydown", { key: "ArrowLeft" });
    expect(w.findAll("[data-test=tab]")[1]!.attributes("aria-selected")).toBe("true");
    await list.trigger("keydown", { key: "Home" });
    expect(w.findAll("[data-test=tab]")[0]!.attributes("aria-selected")).toBe("true");
    await list.trigger("keydown", { key: "End" });
    expect(w.findAll("[data-test=tab]")[1]!.attributes("aria-selected")).toBe("true");
  });

  it("uses a roving tabindex and ties each tab to its panel", async () => {
    const { w } = mountTabs();
    await flushPromises();
    const tabs = w.findAll("[data-test=tab]");
    expect(tabs.map((t) => t.attributes("tabindex"))).toEqual(["0", "-1"]);
    const panel = w.get("[role=tabpanel]");
    expect(panel.attributes("aria-labelledby")).toBe(tabs[0]!.attributes("id"));
    expect(tabs[0]!.attributes("aria-controls")).toBe(panel.attributes("id"));
  });

  it("says so when a tab's tool is not available", async () => {
    const w = mount(GuiTabsSection, { props: { section: SECTION, tools: { tool_b: TOOLS.tool_b }, runTool: vi.fn() } });
    await flushPromises();
    expect(w.text()).toContain("The tool tool_a is not available right now.");
  });
});
