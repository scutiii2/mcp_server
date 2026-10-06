import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GuiFormSectionSpec } from "../api/CapabilityPagesClient";
import type { ToolInfo, ToolRunResult } from "../api/types";
import GuiFormSection from "./GuiFormSection.vue";

vi.mock("../api/CommandsClient", () => ({ commandsClient: { options: vi.fn(), upload: vi.fn() } }));

const TOOL: ToolInfo = {
  name: "tool_a",
  title: "A",
  description: "Makes a thing.",
  inputSchema: { type: "object", properties: { length: { type: "integer", default: 12 } } },
};
const SECTION: GuiFormSectionSpec = {
  type: "form", id: "a", title: "Thing", tool: "tool_a", submit: "Make it", fields: [],
  result: { kind: "secret", field: "code" },
};
const ok = (structured: Record<string, unknown>): ToolRunResult => ({ text: "", isError: false, structured });

describe("GuiFormSection", () => {
  // setImmediate stays real: flushPromises relies on it.
  beforeEach(() => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] }));
  afterEach(() => vi.useRealTimers());

  it("runs the tool with the form's values and shows the result", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "abc" }));
    const w = mount(GuiFormSection, { props: { section: SECTION, tool: TOOL, runTool } });
    expect(w.text()).toContain("Thing");
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(runTool).toHaveBeenCalledWith("tool_a", { length: 12 });
    expect(w.get("[data-test=secret]").text()).toBe("abc");
  });

  it("shows a transport failure inline", async () => {
    const runTool = vi.fn().mockRejectedValue(new Error("mcp_server is unreachable"));
    const w = mount(GuiFormSection, { props: { section: SECTION, tool: TOOL, runTool } });
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(w.text()).toContain("mcp_server is unreachable");
  });

  it("re-runs with the same arguments when the refresh countdown ends", async () => {
    const section = { ...SECTION, result: { kind: "secret", field: "code", refresh_after: "seconds_remaining" } } as GuiFormSectionSpec;
    const runTool = vi.fn()
      .mockResolvedValueOnce(ok({ code: "111111", seconds_remaining: 2 }))
      .mockResolvedValueOnce(ok({ code: "222222", seconds_remaining: 30 }));
    const w = mount(GuiFormSection, { props: { section, tool: TOOL, runTool } });
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(w.text()).toMatch(/2\s*s/);
    vi.advanceTimersByTime(2000);
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(2);
    expect(runTool).toHaveBeenLastCalledWith("tool_a", { length: 12 });
    expect(w.get("[data-test=secret]").text()).toBe("222222");
  });

  it("stops refreshing when unmounted", async () => {
    const section = { ...SECTION, result: { kind: "secret", field: "code", refresh_after: "seconds_remaining" } } as GuiFormSectionSpec;
    const runTool = vi.fn().mockResolvedValue(ok({ code: "1", seconds_remaining: 2 }));
    const w = mount(GuiFormSection, { props: { section, tool: TOOL, runTool } });
    await w.get("form").trigger("submit");
    await flushPromises();
    w.unmount();
    vi.advanceTimersByTime(10_000);
    expect(runTool).toHaveBeenCalledTimes(1);
  });

  it("applies label overrides to the form", () => {
    const section = { ...SECTION, fields: [{ param: "length", label: "How long" }] };
    const w = mount(GuiFormSection, { props: { section, tool: TOOL, runTool: vi.fn() } });
    expect(w.text()).toContain("How long");
  });
});
