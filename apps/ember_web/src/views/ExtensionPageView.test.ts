import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { ExtensionInfo } from "../api/ExtensionsClient";
import type { ToolInfo } from "../api/types";
import ExtensionPageView from "./ExtensionPageView.vue";

const mocks = vi.hoisted(() => ({ list: vi.fn(), listTools: vi.fn(), runTool: vi.fn() }));

vi.mock("../api/ExtensionsClient", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/ExtensionsClient")>()),
  extensionsClient: { list: mocks.list },
}));
vi.mock("../api/McpServerClient", () => ({
  McpServerClient: class {
    listTools = mocks.listTools;
    runTool = mocks.runTool;
  },
}));
vi.mock("../api/CommandsClient", () => ({ commandsClient: { options: vi.fn(), upload: vi.fn() } }));

const tool = (name: string, title: string): ToolInfo => ({
  name,
  title,
  description: `${title} things`,
  inputSchema: { type: "object", properties: {} },
});

const EXT: ExtensionInfo = {
  id: "pdf",
  label: "PDF Merger",
  description: "Merges files.",
  status: "connected",
  error: null,
  tools: ["pdf__merge", "pdf__inspect"],
  web_url: "http://127.0.0.1:5174",
};
const NOTES: ExtensionInfo = { ...EXT, id: "notes", label: "Notes", tools: ["notes__add"], web_url: null };
const TOOLS = [
  tool("pdf__merge", "Merge"),
  tool("pdf__inspect", "Inspect"),
  tool("other__echo", "Echo"),
  tool("tool_gen_generatePin", "Pin"),
];

async function open(path = "/extensions/pdf") {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/capabilities", component: { template: "<div />" } },
      { path: "/extensions/:id", component: ExtensionPageView },
    ],
  });
  await router.push(path);
  const pinia = createPinia();
  setActivePinia(pinia);
  const wrapper = mount(ExtensionPageView, { global: { plugins: [pinia, router] } });
  await flushPromises();
  return { wrapper, router };
}

beforeEach(() => {
  vi.clearAllMocks();
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
  mocks.list.mockResolvedValue([EXT, NOTES]);
  mocks.listTools.mockResolvedValue(TOOLS);
  mocks.runTool.mockResolvedValue({ text: "merged ok", isError: false });
});

describe("ExtensionPageView", () => {
  it("shows the label, description, web app link and only the extension's own tools", async () => {
    const { wrapper } = await open();

    expect(wrapper.text()).toContain("PDF Merger");
    expect(wrapper.text()).toContain("Merges files.");
    const app = wrapper.findAll("a").find((a) => a.text() === "Open app")!;
    expect(app.attributes("href")).toBe("http://127.0.0.1:5174/");
    expect(app.attributes("target")).toBe("_blank");
    expect(app.attributes("rel")).toBe("noopener noreferrer");
    expect(wrapper.findAll("li.tool .title").map((t) => t.text()).sort()).toEqual(["Inspect", "Merge"]);
    expect(wrapper.find('a[href="/capabilities"]').exists()).toBe(true);
  });

  it("has no web app link when the extension names none", async () => {
    const { wrapper } = await open("/extensions/notes");

    expect(wrapper.findAll("a").some((a) => a.text() === "Open app")).toBe(false);
  });

  it("runs a tool from its row and shows the result", async () => {
    const { wrapper } = await open();

    await wrapper
      .findAll("li.tool .row")
      .find((b) => b.text().includes("Merge"))!
      .trigger("click");
    await wrapper.get("dialog form").trigger("submit");
    await flushPromises();

    expect(mocks.runTool).toHaveBeenCalledWith("pdf__merge", {});
    expect(wrapper.get("dialog").text()).toContain("merged ok");
  });

  it("says when the extension is not connected, with its error, and lists no tools", async () => {
    mocks.list.mockResolvedValue([{ ...EXT, status: "error", error: "connection refused", tools: [] }]);
    const { wrapper } = await open();

    expect(wrapper.text()).toMatch(/not connected/i);
    expect(wrapper.text()).toContain("connection refused");
    expect(wrapper.findAll("li.tool")).toHaveLength(0);
    expect(wrapper.findAll("a").some((a) => a.text() === "Open app")).toBe(true);
  });

  it("says when the extension is unknown, with a link back", async () => {
    const { wrapper } = await open("/extensions/nope");

    expect(wrapper.text()).toMatch(/unknown extension/i);
    expect(wrapper.find('a[href="/capabilities"]').exists()).toBe(true);
  });

  it("shows a load failure instead of a half-drawn page", async () => {
    mocks.list.mockRejectedValue(new Error("mcp_server is unreachable"));
    const { wrapper } = await open();

    expect(wrapper.get("[role=alert]").text()).toContain("mcp_server is unreachable");
  });

  it("ignores a slow load for the extension the page just left", async () => {
    let releaseOld!: (value: ExtensionInfo[]) => void;
    mocks.list
      .mockImplementationOnce(() => new Promise<ExtensionInfo[]>((resolve) => (releaseOld = resolve)))
      .mockResolvedValueOnce([NOTES]);
    mocks.listTools.mockResolvedValue([tool("notes__add", "Add note"), ...TOOLS]);
    const { wrapper, router } = await open("/extensions/pdf");

    await router.push("/extensions/notes");
    await flushPromises();
    releaseOld([EXT]);
    await flushPromises();

    expect(wrapper.text()).toContain("Notes");
    expect(wrapper.text()).not.toContain("PDF Merger");
  });
});
