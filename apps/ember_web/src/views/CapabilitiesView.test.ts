import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { Account } from "../api/AuthClient";
import type { CapabilityInfo } from "../api/CommandsClient";
import type { ResourceInfo, ToolInfo } from "../api/types";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import { useAuthStore } from "../stores/auth";
import { useChatStore } from "../stores/chat";
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
  extensionsClient: { list: mocks.extensions, remove: vi.fn(), add: vi.fn() },
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

async function show(options: { admin?: boolean; query?: string; permissions?: string[]; attach?: boolean } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().account = {
    ...ACCOUNT,
    permissions: options.permissions ?? (options.admin ? ["tools.use", "admin.manage"] : ["tools.use"]),
  };
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/capabilities", component: CapabilitiesView },
      { path: "/capabilities/:name", component: { template: "<div />" } },
    ],
  });
  await router.push(options.query ? `/capabilities?q=${options.query}` : "/capabilities");
  const wrapper = mount(CapabilitiesView, {
    attachTo: options.attach ? document.body : undefined,
    global: { plugins: [pinia, router] },
  });
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

  const everyone = (w: Wrapper) => w.get("button.everyone");

  it("gives admins a button in the card that turns a capability on or off for everyone, asking first", async () => {
    mocks.setCapability.mockResolvedValue({ ...CAPS[2]!, enabled: true });
    const w = await show({ admin: true });
    await head(w, "Legacy").trigger("click");
    expect(everyone(w).text()).toBe("Turn on for everyone");

    await everyone(w).trigger("click");
    expect(mocks.setCapability).not.toHaveBeenCalled();
    expect(w.getComponent(ConfirmModal).props("message")).toContain('Turn on "Legacy"');
    expect(w.getComponent(ConfirmModal).props("danger")).toBe(false);
    await w.getComponent(ConfirmModal).get(".confirm").trigger("click");
    await flushPromises();

    expect(mocks.setCapability).toHaveBeenCalledWith("legacy", true);
    expect(head(w, "Legacy").text()).toContain("0 tools");
  });

  it("does not switch anything when the admin declines", async () => {
    const w = await show({ admin: true });
    await head(w, "PDF files").trigger("click");

    await everyone(w).trigger("click");
    await w.getComponent(ConfirmModal).get(".cancel").trigger("click");

    expect(w.findComponent(ConfirmModal).exists()).toBe(false);
    expect(mocks.setCapability).not.toHaveBeenCalled();
  });

  it("marks turning a capability off as a dangerous action", async () => {
    const w = await show({ admin: true });
    await head(w, "PDF files").trigger("click");
    expect(everyone(w).text()).toBe("Turn off for everyone");

    await everyone(w).trigger("click");

    expect(w.getComponent(ConfirmModal).props("message")).toContain("Turn off");
    expect(w.getComponent(ConfirmModal).props("danger")).toBe(true);
  });

  it("shows no everyone button to an account that is not an admin", async () => {
    const w = await show({ permissions: ["tools.use", "chat.use"] });
    await head(w, "PDF files").trigger("click");

    expect(w.find("button.everyone").exists()).toBe(false);
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

describe("CapabilitiesView extension cards", () => {
  const ext = (id: string, webUrl?: string | null, status = "connected") => ({
    id,
    label: id.toUpperCase(),
    description: "",
    status,
    error: status === "error" ? "down" : null,
    tools: [`${id}__run`],
    web_url: webUrl,
  });
  const WITH_CHAT = ["tools.use", "chat.use"];
  const openButtons = (w: Wrapper) =>
    w.findAll("article.card a").filter((a) => a.text() === "Open page" || a.text() === "Open app");

  it("opens the web UI of an extension that has one, in a new tab", async () => {
    mocks.extensions.mockResolvedValue([ext("pdf", "http://127.0.0.1:5174")]);
    const w = await show({ permissions: WITH_CHAT });

    const link = w.get("a[href='http://127.0.0.1:5174/']");
    expect(link.text()).toBe("Open app");
    expect(link.attributes("target")).toBe("_blank");
    expect(link.attributes("rel")).toBe("noopener noreferrer");
  });

  it("gives an extension without a web UI no Open button, and never links a non-http address", async () => {
    mocks.extensions.mockResolvedValue([ext("notes"), ext("odd id/x", null), ext("bad", "javascript:alert(1)")]);
    const w = await show({ permissions: WITH_CHAT });

    expect(openButtons(w).map((a) => [a.text(), a.attributes("href")])).toEqual([
      ["Open page", "/capabilities/pdf"],
    ]);
  });

  it("still opens the web UI when the extension is not connected", async () => {
    mocks.extensions.mockResolvedValue([ext("pdf2", "https://pdf.example", "error")]);
    const w = await show({ permissions: WITH_CHAT });

    expect(w.find("a[href='https://pdf.example/']").exists()).toBe(true);
    expect(head(w, "PDF2").text()).toContain("Not connected");
  });

  it("gives each extension a switch for your chats that applies at once", async () => {
    mocks.extensions.mockResolvedValue([ext("pdf2")]);
    const w = await show({ permissions: WITH_CHAT, attach: true });
    const chat = useChatStore();
    const box = () => w.findAll("input[type=checkbox]").at(-1)!.element as HTMLInputElement;

    expect(box().checked).toBe(false);
    box().click();
    await flushPromises();

    expect(chat.enabledExtensions).toEqual(["pdf2"]);
    expect(box().checked).toBe(true);
    expect(w.findComponent(ConfirmModal).exists()).toBe(false);
    expect(w.findAll(".scope").map((s) => s.text())).toContain("You");

    box().click();
    await flushPromises();

    expect(chat.enabledExtensions).toEqual([]);
    expect(box().checked).toBe(false);
    w.unmount();
  });

  it("does not give an extension a switch without chat.use", async () => {
    mocks.extensions.mockResolvedValue([ext("pdf2")]);
    const w = await show();

    expect(w.findAll("input[type=checkbox]")).toHaveLength(0);
  });

  it("lists only the extensions when the account lacks tools.use", async () => {
    mocks.extensions.mockResolvedValue([ext("pdf2")]);
    const w = await show({ permissions: ["chat.use"] });

    expect(mocks.capabilities).not.toHaveBeenCalled();
    expect(mocks.listTools).not.toHaveBeenCalled();
    expect(sectionNames(w)).toEqual(["PDF2"]);
    expect(w.find(".kinds").exists()).toBe(false);
    expect(openButtons(w)).toHaveLength(0);
  });

  it("filters the cards by kind", async () => {
    mocks.extensions.mockResolvedValue([ext("pdf2")]);
    const w = await show({ permissions: WITH_CHAT });
    const pick = (label: string) => w.findAll(".kinds button").find((b) => b.text() === label)!.trigger("click");

    await pick("Extensions");
    expect(sectionNames(w)).toEqual(["PDF2"]);

    await pick("Built-in");
    expect(sectionNames(w)).toEqual(["PDF files", "services", "Legacy", "Other tools"]);

    await pick("All");
    expect(sectionNames(w)).toEqual(["PDF files", "services", "Legacy", "PDF2", "Other tools"]);
  });

  it("lets only admins add and remove extensions", async () => {
    mocks.extensions.mockResolvedValue([ext("pdf2")]);
    const user = await show({ permissions: WITH_CHAT });
    expect(user.text()).not.toContain("Add extension");

    const admin = await show({ permissions: [...WITH_CHAT, "admin.manage"] });
    expect(admin.text()).toContain("Add extension");
    await head(admin, "PDF2").trigger("click");
    await admin.get("button.danger").trigger("click");
    expect(admin.getComponent(ConfirmModal).props("message")).toContain('Remove "PDF2"');
  });
});

describe("the page layout", () => {
  const ext = (id: string) => ({
    id,
    label: id.toUpperCase(),
    description: "",
    status: "connected",
    error: null,
    tools: [`${id}__run`],
    web_url: null,
  });
  const WITH_CHAT = ["tools.use", "chat.use"];

  it("keeps the long explanation behind a How switches work disclosure", async () => {
    const w = await show();

    expect(w.get("details.how summary").text()).toBe("How switches work");
    expect(w.get(".intro").text()).not.toContain("slash");
    expect(w.get("details.how p").text()).toContain("remembered on this device");
  });

  it("puts the filter and the kind toggle on one row", async () => {
    const w = await show();

    const row = w.get(".toolbar");
    expect(row.find("input[type=search]").exists()).toBe(true);
    expect(row.find(".kinds").exists()).toBe(true);
  });

  it("names the groups and what their switches mean, while All is shown", async () => {
    mocks.extensions.mockResolvedValue([ext("pdf2")]);
    const w = await show({ permissions: WITH_CHAT });

    const titles = w.findAll(".group-title").map((h) => h.text());
    expect(titles).toEqual(["Built-in · switches apply to your chats", "Extensions · switches apply to your chats", "Other"]);

    await w.findAll(".kinds button").find((b) => b.text() === "Built-in")!.trigger("click");
    expect(w.find(".group-title").exists()).toBe(false);
  });

  it("gives each card a tile picture by kind, with its status on the corner", async () => {
    mocks.extensions.mockResolvedValue([ext("pdf2")]);
    const w = await show({ permissions: WITH_CHAT });

    expect(sections(w).every((s) => s.find(".tile svg").exists())).toBe(true);
    expect(sections(w)[0]!.find(".tile .dot").exists()).toBe(true);
  });

  it("lists a capability's tools in one bordered list and labels its resources", async () => {
    const w = await show();
    await head(w, "PDF files").trigger("click");

    expect(w.findAll("ul.cards")).toHaveLength(1);
    expect(w.get(".res-label").text()).toBe("Resources");
    expect(w.find(".resources .res-icon").exists()).toBe(true);
  });
});

describe("built-in switches for your own chats", () => {
  const WITH_CHAT = ["tools.use", "chat.use"];
  const boxes = (w: Wrapper) => w.findAll("input[type=checkbox]");

  it("gives each built-in card a switch for you, on to begin with", async () => {
    const w = await show({ permissions: WITH_CHAT });

    expect(boxes(w)).toHaveLength(3);
    expect(boxes(w).map((b) => (b.element as HTMLInputElement).checked)).toEqual([true, true, false]);
    expect(w.findAll(".scope").map((s) => s.text())).toEqual(["You", "You", "You"]);
  });

  it("switches one off for you at once, without asking, and says so", async () => {
    const w = await show({ permissions: WITH_CHAT, attach: true });
    const chat = useChatStore();

    // Native activation includes checkbox changes and canceled-click rollback.
    (boxes(w)[0]!.element as HTMLInputElement).click();
    await flushPromises();

    expect(chat.disabledCapabilities).toEqual(["pdf"]);
    expect(mocks.setCapability).not.toHaveBeenCalled();
    expect(w.findComponent(ConfirmModal).exists()).toBe(false);
    expect(head(w, "PDF files").text()).toContain("Off for you");
    expect((boxes(w)[0]!.element as HTMLInputElement).checked).toBe(false);

    await head(w, "PDF files").trigger("click");
    expect(w.text()).toContain("Switched off in your chats");

    (boxes(w)[0]!.element as HTMLInputElement).click();
    await flushPromises();
    expect(chat.disabledCapabilities).toEqual([]);
    expect(head(w, "PDF files").text()).toContain("2 tools");
    expect((boxes(w)[0]!.element as HTMLInputElement).checked).toBe(true);
    w.unmount();
  });

  it("keeps the switch of a capability that is off for everyone off, and locked", async () => {
    const w = await show({ permissions: WITH_CHAT });

    const legacy = boxes(w)[2]!.element as HTMLInputElement;
    expect(legacy.checked).toBe(false);
    expect(legacy.disabled).toBe(true);
    expect(head(w, "Legacy").text()).toContain("off");
  });

  it("leaves the everyone switch to admins, inside the card", async () => {
    const w = await show({ permissions: [...WITH_CHAT, "admin.manage"] });
    await head(w, "PDF files").trigger("click");

    expect(w.get("button.everyone").text()).toBe("Turn off for everyone");
  });
});
