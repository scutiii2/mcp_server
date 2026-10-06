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
});
