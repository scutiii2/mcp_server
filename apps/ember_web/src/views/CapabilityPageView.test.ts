import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import { ApiError } from "../api/http";
import type { CapabilityInfo } from "../api/CommandsClient";
import type { ToolInfo } from "../api/types";
import CapabilityPageView from "./CapabilityPageView.vue";

const mocks = vi.hoisted(() => ({ capabilities: vi.fn(), page: vi.fn(), listTools: vi.fn(), runTool: vi.fn() }));

vi.mock("../api/CommandsClient", () => ({ commandsClient: { capabilities: mocks.capabilities, options: vi.fn(), upload: vi.fn() } }));
vi.mock("../api/CapabilityPagesClient", () => ({ capabilityPagesClient: { get: mocks.page } }));
vi.mock("../api/McpServerClient", () => ({
  McpServerClient: class {
    listTools = mocks.listTools;
    runTool = mocks.runTool;
  },
}));

const CAP: CapabilityInfo = { name: "gen", enabled: true, label: "Generator", tools: ["tool_a"], resources: [], has_gui: true };
const TOOL: ToolInfo = { name: "tool_a", title: "A", description: "", inputSchema: { type: "object", properties: {} } };
const PAGE = { version: 1, title: "Generator page", description: "Intro", sections: [{ id: "a", title: "Make", tool: "tool_a", submit: "Go", result: { kind: "message" } }, { id: "n", text: "A note." }] };

async function open(path = "/capabilities/gen") {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/capabilities", component: { template: "<div />" } },
      { path: "/capabilities/:name", component: CapabilityPageView },
    ],
  });
  await router.push(path);
  const w = mount(CapabilityPageView, { global: { plugins: [createPinia(), router] } });
  await flushPromises();
  return w;
}

describe("CapabilityPageView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    Object.values(mocks).forEach((m) => m.mockReset());
    mocks.capabilities.mockResolvedValue([CAP]);
    mocks.page.mockResolvedValue(PAGE);
    mocks.listTools.mockResolvedValue([TOOL]);
  });

  it("draws the title, description, form and text sections", async () => {
    const w = await open();
    expect(w.text()).toContain("Generator page");
    expect(w.text()).toContain("Intro");
    expect(w.text()).toContain("Make");
    expect(w.text()).toContain("A note.");
    expect(w.find('a[href="/capabilities"]').exists()).toBe(true);
    expect(mocks.page).toHaveBeenCalledWith("gen");
  });

  it("says so when the capability has no page", async () => {
    mocks.page.mockRejectedValue(new ApiError(404, "Capability 'gen' has no page"));
    const w = await open();
    expect(w.text()).toMatch(/no page/i);
  });

  it("shows a layout problem instead of a half-drawn page", async () => {
    mocks.page.mockResolvedValue({ ...PAGE, sections: [{ id: "a", title: "x", tool: "tool_zzz" }] });
    const w = await open();
    expect(w.text()).toMatch(/layout/i);
    expect(w.text()).toContain("tool_zzz");
  });

  it("draws a tabs section as tabs", async () => {
    mocks.capabilities.mockResolvedValue([{ ...CAP, tools: ["tool_a", "tool_b"] }]);
    mocks.listTools.mockResolvedValue([TOOL, { ...TOOL, name: "tool_b", title: "B" }]);
    mocks.page.mockResolvedValue({
      version: 1,
      title: "Generator page",
      description: "",
      sections: [{ id: "g", tabs: [
        { id: "a", title: "Alpha", tool: "tool_a", result: { kind: "message" } },
        { id: "b", title: "Beta", tool: "tool_b", result: { kind: "message" } },
      ] }],
    });
    const w = await open();
    expect(w.findAll("[role=tab]").map((t) => t.text())).toEqual(["Alpha", "Beta"]);
  });

  it("says when the capability is off", async () => {
    mocks.capabilities.mockResolvedValue([{ ...CAP, enabled: false }]);
    const w = await open();
    expect(w.text()).toMatch(/turned off/i);
    expect(mocks.page).not.toHaveBeenCalled();
  });

  it("says when the capability is unknown", async () => {
    const w = await open("/capabilities/zzz");
    expect(w.text()).toMatch(/unknown/i);
  });

  describe("overlapping loads", () => {
    function deferred<T>() {
      let resolve!: (v: T) => void;
      let reject!: (e: unknown) => void;
      const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
      return { promise, resolve, reject };
    }
    const CAP_B: CapabilityInfo = { ...CAP, name: "other", label: "Other", tools: ["tool_a"] };

    async function openAThenB() {
      const pageA = deferred<unknown>();
      const pageB = deferred<unknown>();
      mocks.capabilities.mockResolvedValue([CAP, CAP_B]);
      mocks.page.mockImplementation((n: string) => (n === "gen" ? pageA.promise : pageB.promise));
      const router = createRouter({
        history: createMemoryHistory(),
        routes: [
          { path: "/capabilities", component: { template: "<div />" } },
          { path: "/capabilities/:name", component: CapabilityPageView },
        ],
      });
      await router.push("/capabilities/gen");
      const w = mount(CapabilityPageView, { global: { plugins: [createPinia(), router] } });
      await flushPromises();
      await router.push("/capabilities/other");
      await flushPromises();
      return { w, pageA, pageB };
    }

    it("shows the newer page when the older load resolves last", async () => {
      const { w, pageA, pageB } = await openAThenB();
      pageB.resolve({ ...PAGE, title: "Page B" });
      await flushPromises();
      pageA.resolve({ ...PAGE, title: "Page A" });
      await flushPromises();
      expect(w.text()).toContain("Page B");
      expect(w.text()).not.toContain("Page A");
    });

    it("ignores an older load's failure after the newer one succeeded", async () => {
      const { w, pageA, pageB } = await openAThenB();
      pageB.resolve({ ...PAGE, title: "Page B" });
      await flushPromises();
      pageA.reject(new Error("older failure"));
      await flushPromises();
      expect(w.text()).toContain("Page B");
      expect(w.text()).not.toContain("older failure");
    });
  });
});
