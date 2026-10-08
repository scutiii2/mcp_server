import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { Account } from "../api/AuthClient";
import type { CapabilityInfo } from "../api/CommandsClient";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import AddExtensionModal from "../components/AddExtensionModal.vue";
import { useAuthStore } from "../stores/auth";
import SupermarketView from "./SupermarketView.vue";

const mocks = vi.hoisted(() => ({
  capabilities: vi.fn(),
  setCapability: vi.fn(),
  extensions: vi.fn(),
  removeExtension: vi.fn(),
  accountGet: vi.fn(),
  accountSet: vi.fn(),
}));

vi.mock("../api/CommandsClient", () => ({
  commandsClient: { capabilities: mocks.capabilities, setCapability: mocks.setCapability },
}));
vi.mock("../api/ExtensionsClient", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/ExtensionsClient")>()),
  extensionsClient: { list: mocks.extensions, remove: mocks.removeExtension, add: vi.fn() },
}));
vi.mock("../api/AccountCapabilitiesClient", () => ({
  accountCapabilitiesClient: { get: mocks.accountGet, set: mocks.accountSet },
}));

const CAPS: CapabilityInfo[] = [
  { name: "pdf", enabled: true, label: "PDF files", tools: ["tool_pdf_merge", "tool_pdf_split"], resources: [] },
  { name: "calc", enabled: true, label: "Calculator", tools: ["tool_calc"], resources: [] },
  { name: "legacy", enabled: false, label: "Legacy", tools: [], resources: [] },
];
const EXT = { id: "notes", label: "Notes", description: "", status: "connected", error: null, tools: ["notes__add"] };
const BROKEN = { id: "wiki", label: "Wiki", description: "", status: "error", error: "refused", tools: [] };

const ACCOUNT: Account = { id: 1, username: "lex", email: "l@e.com", email_verified: true, roles: [], permissions: [] };

async function show(options: { permissions?: string[]; query?: string; added?: { capabilities?: string[]; extensions?: string[] } } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().account = { ...ACCOUNT, permissions: options.permissions ?? ["tools.use", "chat.use"] };
  mocks.accountGet.mockResolvedValue({
    capabilities: options.added?.capabilities ?? ["pdf"],
    extensions: options.added?.extensions ?? [],
    disabled_tools: [],
  });
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/capabilities", component: { template: "<div />" } },
      { path: "/capabilities/supermarket", component: SupermarketView },
    ],
  });
  await router.push(`/capabilities/supermarket${options.query ? `?${options.query}` : ""}`);
  const wrapper = mount(SupermarketView, { global: { plugins: [pinia, router] } });
  await flushPromises();
  return { w: wrapper, router };
}

type Wrapper = Awaited<ReturnType<typeof show>>["w"];
const rows = (w: Wrapper) => w.findAll("article.item");
const names = (w: Wrapper) => rows(w).map((r) => r.find("h3").text());
const row = (w: Wrapper, label: string) => rows(w).find((r) => r.find("h3").text() === label)!;
const chip = (w: Wrapper, label: string) => w.findAll("button.chip").find((b) => b.text() === label)!;

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
  vi.clearAllMocks();
  mocks.capabilities.mockResolvedValue(CAPS);
  mocks.extensions.mockResolvedValue([EXT, BROKEN]);
  mocks.accountSet.mockImplementation(async () => ({ capabilities: ["pdf", "calc"], extensions: [], disabled_tools: [] }));
});

describe("SupermarketView", () => {
  it("lists built-in capabilities and extensions in two sections", async () => {
    const { w } = await show();

    expect(w.findAll("h4.group-title").map((h) => h.text())).toEqual(["Built-in", "Extensions"]);
    expect(names(w)).toEqual(["Calculator", "Legacy", "PDF files", "Notes", "Wiki"]);
    expect(row(w, "PDF files").find(".summary").text()).toBe("2 tools");
    expect(row(w, "Wiki").find(".summary").text()).toBe("Not connected");
  });

  it("shows Added for what the account has and Add for the rest", async () => {
    const { w } = await show();

    expect(row(w, "PDF files").find(".added").exists()).toBe(true);
    expect(row(w, "Calculator").find("button.add").exists()).toBe(true);
  });

  it("adds a capability for the account", async () => {
    const { w } = await show();

    await row(w, "Calculator").get("button.add").trigger("click");
    await flushPromises();

    expect(mocks.accountSet).toHaveBeenCalledWith("capability", "calc", true);
    expect(row(w, "Calculator").find(".added").exists()).toBe(true);
  });

  it("disables an added extension for the account", async () => {
    const { w } = await show({ added: { capabilities: [], extensions: ["notes"] } });

    await row(w, "Notes").get("button.secondary").trigger("click");
    await flushPromises();

    expect(mocks.accountSet).toHaveBeenCalledWith("extension", "notes", false);
  });

  it("marks a capability that is off for everyone and offers no Add", async () => {
    const { w } = await show();

    expect(row(w, "Legacy").find(".badge").text()).toBe("Off for everyone");
    expect(row(w, "Legacy").find("button.add").exists()).toBe(false);
    expect(row(w, "Legacy").find(".summary").text()).toBe("Off for everyone");
  });

  describe("the Enabled and Disabled chips", () => {
    it("start with neither chosen, showing everything", async () => {
      const { w } = await show();

      expect(chip(w, "Enabled").attributes("aria-pressed")).toBe("false");
      expect(chip(w, "Disabled").attributes("aria-pressed")).toBe("false");
      expect(rows(w)).toHaveLength(5);
    });

    it("Enabled shows only what is added", async () => {
      const { w, router } = await show();

      await chip(w, "Enabled").trigger("click");
      await flushPromises();

      expect(names(w)).toEqual(["PDF files"]);
      expect(router.currentRoute.value.query.state).toBe("enabled");
      expect(chip(w, "Enabled").attributes("aria-pressed")).toBe("true");
    });

    it("Disabled shows only what is not added", async () => {
      const { w } = await show();

      await chip(w, "Disabled").trigger("click");
      await flushPromises();

      expect(names(w)).toEqual(["Calculator", "Legacy", "Notes", "Wiki"]);
    });

    it("choosing the other chip switches, and clicking the active chip clears it", async () => {
      const { w, router } = await show();

      await chip(w, "Enabled").trigger("click");
      await flushPromises();
      await chip(w, "Disabled").trigger("click");
      await flushPromises();
      expect(router.currentRoute.value.query.state).toBe("disabled");

      await chip(w, "Disabled").trigger("click");
      await flushPromises();
      expect(router.currentRoute.value.query.state).toBeUndefined();
      expect(rows(w)).toHaveLength(5);
    });

    it("is read from the address", async () => {
      const { w } = await show({ query: "state=enabled" });

      expect(names(w)).toEqual(["PDF files"]);
    });

    it("says so when a section has nothing in this filter", async () => {
      const { w } = await show({ query: "state=enabled" });

      expect(w.text()).toContain("No extensions match this filter.");
    });
  });

  it("lists only the extensions to an account without tools.use", async () => {
    const { w } = await show({ permissions: ["chat.use"] });

    expect(mocks.capabilities).not.toHaveBeenCalled();
    expect(w.findAll("h4.group-title").map((h) => h.text())).toEqual(["Extensions"]);
    expect(names(w)).toEqual(["Notes", "Wiki"]);
  });

  describe("management permissions", () => {
    const ADMIN = ["tools.use", "chat.use", "admin.manage"];
    const EXTENSION_MANAGER = ["tools.use", "chat.use", "extensions.manage"];

    it("admin.manage alone permits turning on for everyone but hides extension management", async () => {
      const { w } = await show({ permissions: ADMIN });

      expect(w.text()).not.toContain("Add extension");
      expect(w.find("button.remove").exists()).toBe(false);
      expect(w.findComponent(AddExtensionModal).exists()).toBe(false);
      expect(row(w, "Legacy").get("button.everyone").text()).toBe("Turn on for everyone");
    });

    it("extensions.manage alone permits extension management but hides turning on for everyone", async () => {
      const { w } = await show({ permissions: EXTENSION_MANAGER });

      expect(w.text()).toContain("Add extension");
      expect(row(w, "Notes").get("button.remove").text()).toBe("Remove");
      expect(row(w, "Legacy").find("button.everyone").exists()).toBe(false);
      await w.get("button.primary").trigger("click");
      expect(w.getComponent(AddExtensionModal).props("open")).toBe(true);
    });

    it("add and remove extensions; others see neither", async () => {
      const user = await show();
      expect(user.w.text()).not.toContain("Add extension");
      expect(user.w.find("button.remove").exists()).toBe(false);

      const manager = await show({ permissions: EXTENSION_MANAGER });
      expect(manager.w.text()).toContain("Add extension");
      await row(manager.w, "Notes").get("button.remove").trigger("click");
      expect(manager.w.getComponent(ConfirmModal).props("message")).toContain('Remove "Notes"');
    });

    it("removing an extension asks the server and reloads the account's choices", async () => {
      mocks.removeExtension.mockResolvedValue(undefined);
      const { w } = await show({ permissions: EXTENSION_MANAGER, added: { extensions: ["notes"] } });
      await row(w, "Notes").get("button.remove").trigger("click");

      await w.getComponent(ConfirmModal).get(".confirm").trigger("click");
      await flushPromises();

      expect(mocks.removeExtension).toHaveBeenCalledWith("notes");
      expect(names(w)).not.toContain("Notes");
      expect(mocks.accountGet).toHaveBeenCalledTimes(2);
    });

    it("can turn a capability that is off for everyone back on, asking first", async () => {
      mocks.setCapability.mockResolvedValue({ ...CAPS[2]!, enabled: true });
      const { w } = await show({ permissions: ADMIN });

      await row(w, "Legacy").get("button.everyone").trigger("click");
      expect(w.getComponent(ConfirmModal).props("message")).toContain('Turn on "Legacy"');
      await w.getComponent(ConfirmModal).get(".confirm").trigger("click");
      await flushPromises();

      expect(mocks.setCapability).toHaveBeenCalledWith("legacy", true);
      expect(row(w, "Legacy").find(".badge").exists()).toBe(false);
    });

    it("shows no everyone button on a capability that is on for everyone", async () => {
      const { w } = await show({ permissions: ADMIN });

      expect(row(w, "PDF files").find("button.everyone").exists()).toBe(false);
    });
  });

  it("shows why a change failed", async () => {
    mocks.accountSet.mockRejectedValue(new Error("Too many items added to this account"));
    const { w } = await show();

    await row(w, "Calculator").get("button.add").trigger("click");
    await flushPromises();

    expect(w.get("[role=alert]").text()).toContain("Too many items added to this account");
  });

  it("reports a load failure", async () => {
    mocks.capabilities.mockRejectedValue(new Error("mcp_server is down"));
    const { w } = await show();

    expect(w.text()).toContain("mcp_server is down");
  });
});
