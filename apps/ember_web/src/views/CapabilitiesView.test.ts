import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { Account } from "../api/AuthClient";
import type { CapabilityInfo } from "../api/CommandsClient";
import type { ResourceInfo, ToolInfo } from "../api/types";
import { useAuthStore } from "../stores/auth";
import CapabilitiesView from "./CapabilitiesView.vue";

const mocks = vi.hoisted(() => ({
  capabilities: vi.fn(),
  setCapability: vi.fn(),
  listTools: vi.fn(),
  listResources: vi.fn(),
  readResource: vi.fn(),
  runTool: vi.fn(),
  extensions: vi.fn(),
}));

vi.mock("../api/ExtensionsClient", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/ExtensionsClient")>()),
  extensionsClient: { list: mocks.extensions },
}));

vi.mock("../api/CommandsClient", () => ({
  commandsClient: { capabilities: mocks.capabilities, setCapability: mocks.setCapability },
}));
vi.mock("../api/McpServerClient", () => ({
  McpServerClient: class {
    listTools = mocks.listTools;
    listResources = mocks.listResources;
    readResource = mocks.readResource;
    runTool = mocks.runTool;
  },
}));

const tool = (name: string, title: string, description = ""): ToolInfo => ({
  name,
  title,
  description,
  inputSchema: { type: "object", properties: {} },
});

const CAPS: CapabilityInfo[] = [
  { name: "pdf", enabled: true, label: "PDF files", tools: ["tool_pdf_merge", "tool_pdf_split"], resources: ["pdf_help"], has_gui: true },
  { name: "services", enabled: true, label: null, tools: ["tool_srv_restart"], resources: [] },
  { name: "legacy", enabled: false, label: "Legacy", tools: [], resources: [] },
];
const TOOLS = [
  tool("tool_pdf_merge", "Merge", "Join PDFs"),
  tool("tool_pdf_split", "Split"),
  tool("tool_srv_restart", "Restart Service"),
  tool("ext__echo", "Echo"),
];
const RESOURCES: ResourceInfo[] = [{ uri: "help://pdf", name: "pdf_help", description: "How to merge", template: false }];

const ACCOUNT: Account = {
  id: 1,
  username: "lex",
  email: "lex@example.com",
  email_verified: true,
  roles: [],
  permissions: ["tools.use"],
};

async function show(options: { admin?: boolean; query?: string } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().account = {
    ...ACCOUNT,
    permissions: options.admin ? ["tools.use", "admin.manage"] : ["tools.use"],
  };
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/capabilities", component: CapabilitiesView },
      { path: "/capabilities/:name", component: { template: "<div />" } },
    ],
  });
  await router.push(options.query ? `/capabilities?q=${options.query}` : "/capabilities");
  const wrapper = mount(CapabilitiesView, { global: { plugins: [pinia, router] } });
  await flushPromises();
  return wrapper;
}

type Wrapper = Awaited<ReturnType<typeof show>>;
const sections = (w: Wrapper) => w.findAll("article.card");
const sectionNames = (w: Wrapper) => sections(w).map((s) => s.find("h3").text());
const head = (w: Wrapper, name: string) =>
  w.findAll("article.card .head-button").find((b) => b.find("h3").text() === name)!;
const toolTitles = (w: Wrapper) => w.findAll("li.tool .title").map((t) => t.text());
const toolRows = (w: Wrapper) => w.findAll("li.tool .row");
const modal = (w: Wrapper) => w.get("dialog.modal");

beforeEach(() => {
  // jsdom has no modal dialogs.
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
  vi.clearAllMocks();
  mocks.capabilities.mockResolvedValue(CAPS);
  mocks.listTools.mockResolvedValue(TOOLS);
  mocks.listResources.mockResolvedValue(RESOURCES);
  mocks.extensions.mockResolvedValue([]);
  mocks.runTool.mockResolvedValue({ text: "merged ok", isError: false });
  mocks.readResource.mockResolvedValue("# Help text");
  vi.stubGlobal("confirm", vi.fn(() => true));
});

describe("CapabilitiesView", () => {
  it("links a capability that has a page to it, and only that one", async () => {
    const w = await show();

    const links = w.findAll("a").filter((a) => a.text() === "Open page");

    expect(links).toHaveLength(1);
    expect(links[0].attributes("href")).toBe("/capabilities/pdf");
  });

  it("lists every capability collapsed, with what it brings", async () => {
    const w = await show();

    expect(sectionNames(w)).toEqual(["PDF files", "services", "Legacy", "Other tools"]);
    expect(toolTitles(w)).toEqual([]);
    expect(head(w, "PDF files").attributes("aria-expanded")).toBe("false");
    expect(head(w, "PDF files").text()).toContain("2 tools · 1 resource");
    expect(head(w, "services").text()).toContain("1 tool");
    expect(head(w, "Legacy").text()).toContain("off");
  });

  it("opens and closes a capability from its header", async () => {
    const w = await show();

    await head(w, "PDF files").trigger("click");
    expect(toolTitles(w)).toEqual(["Merge", "Split"]);
    expect(head(w, "PDF files").attributes("aria-expanded")).toBe("true");

    await head(w, "PDF files").trigger("click");
    expect(toolTitles(w)).toEqual([]);
  });

  it("lists the tools no capability claims under 'Other tools'", async () => {
    const w = await show();

    await head(w, "Other tools").trigger("click");

    expect(toolTitles(w)).toEqual(["Echo"]);
  });

  describe("extensions", () => {
    const EXT = {
      id: "ext",
      label: "Echo server",
      description: "",
      status: "connected",
      error: null,
      tools: ["ext__echo"],
      web_url: "https://echo.example/app",
    };

    it("gives each extension its own accordion instead of 'Other tools'", async () => {
      mocks.extensions.mockResolvedValue([EXT]);
      const w = await show();

      expect(sectionNames(w)).toEqual(["PDF files", "services", "Legacy", "Echo server"]);
      expect(head(w, "Echo server").text()).toContain("1 tool");

      await head(w, "Echo server").trigger("click");
      expect(toolTitles(w)).toEqual(["Echo"]);
      expect(w.get("a[href='https://echo.example/app']").text()).toBe("Open app");
    });

    it("lists its resources, namespaced by its id, and keeps the rest under 'Other tools'", async () => {
      mocks.extensions.mockResolvedValue([EXT]);
      mocks.listResources.mockResolvedValue([
        ...RESOURCES,
        { uri: "x://notes", name: "ext__notes", description: "", template: false },
        { uri: "x://stray", name: "stray", description: "", template: false },
      ]);
      const w = await show();

      expect(head(w, "Echo server").text()).toContain("1 tool · 1 resource");
      await head(w, "Echo server").trigger("click");
      expect(w.findAll("button.link").map((b) => b.text())).toEqual(["ext__notes"]);

      await head(w, "Other tools").trigger("click");
      expect(w.findAll("button.link").map((b) => b.text())).toEqual(["ext__notes", "stray"]);
    });

    it("shows why an extension that is not connected has no tools", async () => {
      mocks.extensions.mockResolvedValue([{ ...EXT, status: "error", error: "refused", tools: [], web_url: null }]);
      mocks.listTools.mockResolvedValue(TOOLS.filter((t) => t.name !== "ext__echo"));
      const w = await show();

      await head(w, "Echo server").trigger("click");

      expect(w.text()).toContain("Not connected: refused");
      expect(w.find("a[target=_blank]").exists()).toBe(false);
    });

    it("still loads the page when the extensions list fails", async () => {
      mocks.extensions.mockRejectedValue(new Error("403"));
      const w = await show();

      expect(sectionNames(w)).toEqual(["PDF files", "services", "Legacy", "Other tools"]);
    });
  });

  it("explains a capability that is switched off", async () => {
    const w = await show();

    await head(w, "Legacy").trigger("click");

    expect(w.text()).toContain("Turned off");
  });

  it("opens the matching capabilities while a filter is typed, and shows only matching tools", async () => {
    const w = await show();

    await w.get("input[type=search]").setValue("split");

    expect(sectionNames(w)).toEqual(["PDF files"]);
    expect(toolTitles(w)).toEqual(["Split"]);

    await w.get("input[type=search]").setValue("");
    expect(sectionNames(w)).toEqual(["PDF files", "services", "Legacy", "Other tools"]);
    expect(toolTitles(w)).toEqual([]);
  });

  it("prefills the filter from ?q=", async () => {
    const w = await show({ query: "restart" });

    expect((w.get("input[type=search]").element as HTMLInputElement).value).toBe("restart");
    expect(toolTitles(w)).toEqual(["Restart Service"]);
  });

  it("says so when nothing matches the filter", async () => {
    const w = await show();

    await w.get("input[type=search]").setValue("zzz");

    expect(sections(w)).toHaveLength(0);
    expect(w.text()).toContain('Nothing matches "zzz"');
  });

  it("shows a tool as just its label and name", async () => {
    const w = await show();
    await head(w, "PDF files").trigger("click");

    const row = toolRows(w)[0]!;
    expect(row.text()).toContain("Merge");
    expect(row.text()).toContain("tool_pdf_merge");
    expect(row.text()).not.toContain("Join PDFs");
    expect(modal(w).attributes("open")).toBeUndefined();
  });

  it("opens a modal with the tool's description and parameters when its row is pressed", async () => {
    const w = await show();
    await head(w, "PDF files").trigger("click");

    await toolRows(w)[0]!.trigger("click");
    await flushPromises();

    expect(modal(w).attributes("open")).toBeDefined();
    expect(modal(w).text()).toContain("Merge");
    expect(modal(w).text()).toContain("Join PDFs");
    expect(modal(w).find("form.tool-form").exists()).toBe(true);
  });

  it("runs the tool from the modal and shows its result there", async () => {
    const w = await show();
    await head(w, "PDF files").trigger("click");
    await toolRows(w)[0]!.trigger("click");
    await flushPromises();

    await modal(w).get("form.tool-form").trigger("submit");
    await flushPromises();

    expect(mocks.runTool).toHaveBeenCalledWith("tool_pdf_merge", {});
    expect(modal(w).text()).toContain("merged ok");
  });

  it("closes the modal from its close button and forgets the result", async () => {
    const w = await show();
    await head(w, "PDF files").trigger("click");
    await toolRows(w)[0]!.trigger("click");
    await flushPromises();
    await modal(w).get("form.tool-form").trigger("submit");
    await flushPromises();

    await modal(w).get("button.close").trigger("click");
    await flushPromises();
    expect(modal(w).attributes("open")).toBeUndefined();

    await toolRows(w)[0]!.trigger("click");
    await flushPromises();
    expect(modal(w).text()).not.toContain("merged ok");
  });

  it("reads a resource of an open capability", async () => {
    const w = await show();
    await head(w, "PDF files").trigger("click");

    await w.get("button.link").trigger("click");
    await flushPromises();

    expect(mocks.readResource).toHaveBeenCalledWith("help://pdf");
    expect(w.text()).toContain("Help text");
  });

  it("gives admins an on/off switch that asks first and then switches", async () => {
    mocks.setCapability.mockResolvedValue({ ...CAPS[2]!, enabled: true });
    const w = await show({ admin: true });

    await w.findAll("input[type=checkbox]")[2]!.trigger("click");
    await flushPromises();

    expect(confirm).toHaveBeenCalled();
    expect(mocks.setCapability).toHaveBeenCalledWith("legacy", true);
    expect(head(w, "Legacy").text()).toContain("0 tools");
  });

  it("does not switch anything when the admin declines", async () => {
    vi.stubGlobal("confirm", vi.fn(() => false));
    const w = await show({ admin: true });

    await w.findAll("input[type=checkbox]")[0]!.trigger("click");

    expect(mocks.setCapability).not.toHaveBeenCalled();
  });

  it("shows other users a plain On/Off badge and no switch", async () => {
    const w = await show();

    expect(w.findAll("input[type=checkbox]")).toHaveLength(0);
    expect(w.findAll(".badge").map((b) => b.text())).toEqual(["On", "On", "Off"]);
  });

  it("reports a load failure", async () => {
    mocks.capabilities.mockRejectedValue(new Error("server down"));
    const w = await show();

    expect(w.text()).toContain("server down");
    expect(sections(w)).toHaveLength(0);
  });
});
