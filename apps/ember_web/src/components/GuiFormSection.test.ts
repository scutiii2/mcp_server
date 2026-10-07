import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h, KeepAlive } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GuiFormSectionSpec } from "../api/CapabilityPagesClient";
import type { ToolInfo, ToolRunResult } from "../api/types";
import GuiFormSection from "./GuiFormSection.vue";

/** The component's `runTool` prop; a bare `vi.fn()` mock needs a cast to it. */
type RunTool = InstanceType<typeof GuiFormSection>["$props"]["runTool"];

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

  it("does not restart the countdown when a run resolves after unmount", async () => {
    const section = { ...SECTION, result: { kind: "secret", field: "code", refresh_after: "seconds_remaining" } } as GuiFormSectionSpec;
    let resolve!: (r: ToolRunResult) => void;
    const runTool = vi.fn().mockReturnValue(new Promise<ToolRunResult>((r) => { resolve = r; }));
    const w = mount(GuiFormSection, { props: { section, tool: TOOL, runTool } });
    await w.get("form").trigger("submit");
    w.unmount();
    resolve(ok({ code: "1", seconds_remaining: 2 }));
    await flushPromises();
    vi.advanceTimersByTime(10_000);
    expect(runTool).toHaveBeenCalledTimes(1);
  });

  it("keeps the newest result when an older run resolves last", async () => {
    const resolvers: Array<(r: ToolRunResult) => void> = [];
    const runTool = vi.fn().mockImplementation(() => new Promise<ToolRunResult>((r) => { resolvers.push(r); }));
    const w = mount(GuiFormSection, { props: { section: SECTION, tool: TOOL, runTool } });
    await w.get("form").trigger("submit");
    await w.get("form").trigger("submit");
    resolvers[1](ok({ code: "new" }));
    await flushPromises();
    resolvers[0](ok({ code: "old" }));
    await flushPromises();
    expect(w.get("[data-test=secret]").text()).toBe("new");
  });

  it("shows a ring beside the countdown text", async () => {
    const section = { ...SECTION, result: { kind: "secret", field: "code", refresh_after: "seconds_remaining" } } as GuiFormSectionSpec;
    const runTool = vi.fn().mockResolvedValue(ok({ code: "1", seconds_remaining: 30 }));
    const w = mount(GuiFormSection, { props: { section, tool: TOOL, runTool } });
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(w.find("svg.ring").exists()).toBe(true);
    expect(w.text()).toContain("New code in 30 s");
  });
});

const LIVE_TOOL: ToolInfo = {
  name: "tool_a",
  title: "A",
  description: "",
  inputSchema: { type: "object", properties: { length: { type: "integer", minimum: 8, maximum: 128, default: 20, input: "range" } } },
};
const LIVE: GuiFormSectionSpec = { ...SECTION, live: true };
function deferred() {
  let resolve!: (v: ToolRunResult) => void;
  const promise = new Promise<ToolRunResult>((r) => (resolve = r));
  return { promise, resolve };
}

describe("GuiFormSection live", () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] }));
  afterEach(() => vi.useRealTimers());

  it("runs as soon as it opens, with no Run button", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "abc" }));
    const w = mount(GuiFormSection, { props: { section: LIVE, tool: LIVE_TOOL, runTool } });
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(1);
    expect(runTool).toHaveBeenCalledWith("tool_a", { length: 20 });
    expect(w.find("button.run").exists()).toBe(false);
    expect(w.get("[data-test=secret]").text()).toBe("abc");
  });

  it("waits 300 ms after a change and runs once for a burst of changes", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "abc" }));
    const w = mount(GuiFormSection, { props: { section: LIVE, tool: LIVE_TOOL, runTool } });
    await flushPromises();
    const slider = w.get("input[type=range]");
    for (const value of ["30", "40", "50"]) {
      await slider.setValue(value);
      await slider.trigger("change");
    }
    vi.advanceTimersByTime(299);
    expect(runTool).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(2);
    expect(runTool).toHaveBeenLastCalledWith("tool_a", { length: 50 });
  });

  it("Generate again runs with the same arguments", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "abc" }));
    const w = mount(GuiFormSection, { props: { section: LIVE, tool: LIVE_TOOL, runTool } });
    await flushPromises();
    await w.get("[data-test=again]").trigger("click");
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(2);
    expect(runTool).toHaveBeenLastCalledWith("tool_a", { length: 20 });
  });

  it("Generate again is disabled while a run is pending and enabled when it resolves", async () => {
    const pending = deferred();
    const runTool = vi.fn().mockReturnValueOnce(Promise.resolve(ok({ code: "abc" }))).mockReturnValueOnce(pending.promise);
    const w = mount(GuiFormSection, { props: { section: LIVE, tool: LIVE_TOOL, runTool } });
    await flushPromises();
    expect(w.get("[data-test=again]").attributes("disabled")).toBeUndefined();
    await w.get("[data-test=again]").trigger("click");
    expect(w.get("[data-test=again]").attributes("disabled")).toBeDefined();
    await w.get("[data-test=again]").trigger("click");
    expect(runTool).toHaveBeenCalledTimes(2);
    pending.resolve(ok({ code: "def" }));
    await flushPromises();
    expect(w.get("[data-test=again]").attributes("disabled")).toBeUndefined();
  });

  it("an embedded section shows a failed run's error in the embedded layout", async () => {
    const runTool = vi.fn().mockRejectedValue(new Error("mcp_server is unreachable"));
    const w = mount(GuiFormSection, { props: { section: LIVE, tool: LIVE_TOOL, runTool, embedded: true } });
    await flushPromises();
    expect(w.classes()).toContain("embedded");
    expect(w.get("p.error").text()).toContain("mcp_server is unreachable");
  });

  it("a form that is not live has no Generate again button", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "abc" }));
    const w = mount(GuiFormSection, { props: { section: SECTION, tool: TOOL, runTool } });
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(w.find("[data-test=again]").exists()).toBe(false);
  });

  it("drops the title and description and adds the embedded class when embedded", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "abc" }));
    const w = mount(GuiFormSection, { props: { section: LIVE, tool: { ...LIVE_TOOL, description: "Makes a thing." }, runTool, embedded: true } });
    await flushPromises();
    expect(w.find("h3").exists()).toBe(false);
    expect(w.text()).not.toContain("Makes a thing.");
    expect(w.classes()).toContain("embedded");
  });
});

describe("GuiFormSection inside KeepAlive", () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] }));
  afterEach(() => vi.useRealTimers());

  const REFRESHING = { ...SECTION, result: { kind: "secret", field: "code", refresh_after: "seconds_remaining" } } as GuiFormSectionSpec;

  function host(runTool: ReturnType<typeof vi.fn>) {
    return mount(
      defineComponent({
        props: { on: { type: Boolean, default: true } },
        setup: (props) => () =>
          h(KeepAlive, null, { default: () => (props.on ? h(GuiFormSection, { section: REFRESHING, tool: TOOL, runTool: runTool as RunTool }) : null) }),
      }),
    );
  }

  it("stops refreshing while hidden and refreshes again when shown", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "1", seconds_remaining: 5 }));
    const w = host(runTool);
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(1);

    await w.setProps({ on: false });
    vi.advanceTimersByTime(20_000);
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(1);

    await w.setProps({ on: true });
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(2);
  });
});

describe("GuiFormSection lifecycle", () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] }));
  afterEach(() => vi.useRealTimers());

  const REFRESH: GuiFormSectionSpec["result"] = { kind: "secret", field: "code", refresh_after: "seconds_remaining" };
  const REFRESHING = { ...SECTION, result: REFRESH } as GuiFormSectionSpec;
  const LIVE_REFRESHING = { ...LIVE, result: REFRESH } as GuiFormSectionSpec;

  function host(section: GuiFormSectionSpec, tool: ToolInfo, runTool: ReturnType<typeof vi.fn>) {
    return mount(
      defineComponent({
        props: { on: { type: Boolean, default: true } },
        setup: (props) => () =>
          h(KeepAlive, null, { default: () => (props.on ? h(GuiFormSection, { section, tool, runTool: runTool as RunTool }) : null) }),
      }),
    );
  }

  it("a run that resolves while hidden is stored but starts no countdown", async () => {
    const late = deferred();
    const runTool = vi.fn().mockResolvedValueOnce(ok({ code: "1", seconds_remaining: 5 })).mockReturnValueOnce(late.promise);
    const w = host(REFRESHING, TOOL, runTool);
    await w.get("form").trigger("submit");
    await flushPromises();
    vi.advanceTimersByTime(5000);
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(2);

    await w.setProps({ on: false });
    late.resolve(ok({ code: "2", seconds_remaining: 5 }));
    await flushPromises();
    vi.advanceTimersByTime(20_000);
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(2);

    await w.setProps({ on: true });
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(3);
  });

  it("a live section with refresh_after runs exactly once on first open", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "1", seconds_remaining: 30 }));
    host(LIVE_REFRESHING, LIVE_TOOL, runTool);
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(1);
  });

  it("a live section without refresh_after does not run again when re-activated", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "1" }));
    const w = host(LIVE, LIVE_TOOL, runTool);
    await flushPromises();
    await w.setProps({ on: false });
    await w.setProps({ on: true });
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(1);
  });

  it("a pending debounce is cleared on deactivate", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "1" }));
    const w = host(LIVE, LIVE_TOOL, runTool);
    await flushPromises();
    await w.get("input[type=range]").setValue("40");
    await w.get("input[type=range]").trigger("change");
    vi.advanceTimersByTime(100);
    await w.setProps({ on: false });
    vi.advanceTimersByTime(1000);
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(1);
  });

  it("a change pending at deactivate runs once on re-activation with the new args", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "1" }));
    const w = host(LIVE, LIVE_TOOL, runTool);
    await flushPromises();
    await w.get("input[type=range]").setValue("40");
    await w.get("input[type=range]").trigger("change");
    vi.advanceTimersByTime(100);
    await w.setProps({ on: false });
    vi.advanceTimersByTime(1000);
    await w.setProps({ on: true });
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(2);
    expect(runTool).toHaveBeenLastCalledWith("tool_a", { length: 40 });
    vi.advanceTimersByTime(1000);
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(2);
  });

  it("with refresh_after a pending change still gives exactly one run on re-activation", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "1", seconds_remaining: 30 }));
    const w = host(LIVE_REFRESHING, LIVE_TOOL, runTool);
    await flushPromises();
    await w.get("input[type=range]").setValue("40");
    await w.get("input[type=range]").trigger("change");
    vi.advanceTimersByTime(100);
    await w.setProps({ on: false });
    await w.setProps({ on: true });
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(2);
    expect(runTool).toHaveBeenLastCalledWith("tool_a", { length: 40 });
  });

  it("unmounting during a pending debounce does not run", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "1" }));
    const w = mount(GuiFormSection, { props: { section: LIVE, tool: LIVE_TOOL, runTool } });
    await flushPromises();
    await w.get("input[type=range]").setValue("40");
    await w.get("input[type=range]").trigger("change");
    w.unmount();
    vi.advanceTimersByTime(1000);
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(1);
  });

  it("unmounting during an in-flight run starts no countdown", async () => {
    const pending = deferred();
    const runTool = vi.fn().mockReturnValue(pending.promise);
    const w = mount(GuiFormSection, { props: { section: LIVE_REFRESHING, tool: LIVE_TOOL, runTool } });
    await flushPromises();
    w.unmount();
    pending.resolve(ok({ code: "1", seconds_remaining: 5 }));
    await flushPromises();
    vi.advanceTimersByTime(20_000);
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(1);
  });

  it("a live change during a run drops the older result and shows the newest", async () => {
    const first = deferred();
    const second = deferred();
    const runTool = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const w = mount(GuiFormSection, { props: { section: LIVE, tool: LIVE_TOOL, runTool } });
    await flushPromises();
    await w.get("input[type=range]").setValue("40");
    await w.get("input[type=range]").trigger("change");
    vi.advanceTimersByTime(300);
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(2);
    second.resolve(ok({ code: "new" }));
    await flushPromises();
    first.resolve(ok({ code: "old" }));
    await flushPromises();
    expect(w.get("[data-test=secret]").text()).toBe("new");
  });

  it("a live run that rejects shows the error and starts no countdown", async () => {
    const runTool = vi.fn().mockRejectedValue(new Error("mcp_server is unreachable"));
    const w = mount(GuiFormSection, { props: { section: LIVE_REFRESHING, tool: LIVE_TOOL, runTool } });
    await flushPromises();
    expect(w.text()).toContain("mcp_server is unreachable");
    expect(w.find(".refresh").exists()).toBe(false);
  });
});
