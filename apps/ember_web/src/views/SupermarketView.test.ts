import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { Account } from "../api/AuthClient";
import type { CapabilityInfo } from "../api/CommandsClient";
import type { UserExtension } from "../api/UserExtensionsClient";
import ConfirmModal from "../components/ConfirmModal.vue";
import UserExtensionModal from "../components/UserExtensionModal.vue";
import { useAuthStore } from "../stores/auth";
import SupermarketView from "./SupermarketView.vue";

const mocks = vi.hoisted(() => ({
  capabilities: vi.fn(),
  setCapability: vi.fn(),
  extensions: vi.fn(),
  removeExtension: vi.fn(),
  accountGet: vi.fn(),
  accountSet: vi.fn(),
  userList: vi.fn(),
  userCreate: vi.fn(),
  userUpdate: vi.fn(),
  userRemove: vi.fn(),
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
vi.mock("../api/UserExtensionsClient", () => ({
  userExtensionsClient: {
    list: mocks.userList,
    create: mocks.userCreate,
    update: mocks.userUpdate,
    remove: mocks.userRemove,
  },
}));

const CAPS: CapabilityInfo[] = [
  { name: "pdf", enabled: true, label: "PDF files", tools: ["tool_pdf_merge", "tool_pdf_split"], resources: [] },
  { name: "calc", enabled: true, label: "Calculator", tools: ["tool_calc"], resources: [] },
  { name: "legacy", enabled: false, label: "Legacy", tools: [], resources: [] },
];
const EXT = { id: "notes", label: "Notes", description: "", status: "connected", error: null, tools: ["notes__add"] };
const BROKEN = { id: "wiki", label: "Wiki", description: "", status: "error", error: "refused", tools: [] };
const MINE: UserExtension = {
  id: "mynotes",
  label: "My notes",
  description: "",
  url: "https://notes.example.com/mcp",
  header_names: ["X-Key"],
  enabled: true,
  status: "connected",
  error: null,
  tools: ["search", "add"],
};
const MINE_OFF: UserExtension = { ...MINE, id: "draft", label: "Draft", enabled: false, status: "unknown", tools: [] };
const MINE_DOWN: UserExtension = {
  ...MINE,
  id: "flaky",
  label: "Flaky",
  status: "error",
  error: "That address is not allowed",
  tools: [],
};

const ACCOUNT: Account = { id: 1, username: "lex", email: "l@e.com", email_verified: true, roles: [], permissions: [] };

async function show(
  options: {
    permissions?: string[];
    query?: string;
    added?: { capabilities?: string[]; extensions?: string[] };
    userExtensions?: UserExtension[];
  } = {},
) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().account = { ...ACCOUNT, permissions: options.permissions ?? ["tools.view", "chat.use", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"] };
  mocks.accountGet.mockResolvedValue({
    capabilities: options.added?.capabilities ?? ["pdf"],
    extensions: options.added?.extensions ?? [],
    disabled_tools: [],
  });
  mocks.userList.mockResolvedValue(options.userExtensions ?? []);
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
  mocks.userUpdate.mockImplementation(async (id: string, patch: Partial<UserExtension>) => ({
    ...[MINE, MINE_OFF, MINE_DOWN].find((item) => item.id === id)!,
    ...patch,
  }));
});

describe("SupermarketView", () => {
  it("lists built-in capabilities and extensions in two sections", async () => {
    const { w } = await show();

    expect(w.findAll("h4.group-title").map((h) => h.text())).toEqual(["Built-in", "Extensions", "My extensions"]);
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

  it("lists only the extensions to an account without tools.view", async () => {
    const { w } = await show({ permissions: ["chat.use", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"] });

    expect(mocks.capabilities).not.toHaveBeenCalled();
    expect(w.findAll("h4.group-title").map((h) => h.text())).toEqual(["Extensions", "My extensions"]);
    expect(names(w)).toEqual(["Notes", "Wiki"]);
  });

  it("leaves shared extension and global capability management in Ember Admin", async () => {
    const { w } = await show({ permissions: ["tools.view", "chat.use", "roles.manage", "extensions.manage", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"] });
    expect(w.text()).not.toContain("Add extension");
    expect(row(w, "Notes").find("button.remove").exists()).toBe(false);
    expect(row(w, "Legacy").find("button.everyone").exists()).toBe(false);
    expect(w.text()).toContain("Add your own extension");
    expect(row(w, "Calculator").find("button.add").exists()).toBe(true);
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

describe("My extensions", () => {
  const privateRows = (w: Wrapper) => rows(w).filter((r) => r.find("button.edit").exists());
  const addButton = (w: Wrapper) => w.findAll("button.primary").find((b) => b.text() === "Add your own extension")!;

  it("lists the account's own extensions with what each brings", async () => {
    const { w } = await show({ userExtensions: [MINE, MINE_OFF, MINE_DOWN] });

    expect(privateRows(w).map((r) => r.find("h3").text())).toEqual(["Draft", "Flaky", "My notes"]);
    expect(row(w, "My notes").find(".summary").text()).toBe("2 tools");
    expect(row(w, "Draft").find(".summary").text()).toBe("Not enabled");
    expect(row(w, "Flaky").find(".summary").text()).toBe("Not connected");
    expect(row(w, "Flaky").find(".detail").text()).toBe("That address is not allowed");
  });

  it("says so when there are none", async () => {
    const { w } = await show();

    expect(w.text()).toContain("You haven't added any private extensions.");
    expect(w.text()).toContain("Add your own extension");
  });

  it("is there for an account with only chat.use", async () => {
    const { w } = await show({ permissions: ["chat.use", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"], userExtensions: [MINE] });

    expect(names(w)).toContain("My notes");
  });

  it("is not there without chat.use", async () => {
    const { w } = await show({ permissions: ["tools.view", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"], userExtensions: [MINE] });

    expect(w.text()).not.toContain("My extensions");
    expect(mocks.userList).not.toHaveBeenCalled();
  });

  it("enables and disables with Enable and Disable", async () => {
    const { w } = await show({ userExtensions: [MINE, MINE_OFF] });

    expect(row(w, "Draft").get("button.add").text()).toBe("Enable");
    expect(row(w, "My notes").get(".added").text()).toContain("Enabled");

    await row(w, "Draft").get("button.add").trigger("click");
    await flushPromises();
    expect(mocks.userUpdate).toHaveBeenCalledWith("draft", { enabled: true });
    expect(row(w, "Draft").find(".added").exists()).toBe(true);

    await row(w, "My notes").get("button.secondary").trigger("click");
    await flushPromises();
    expect(mocks.userUpdate).toHaveBeenCalledWith("mynotes", { enabled: false });
  });

  it("follows the Enabled and Disabled chips", async () => {
    const { w } = await show({ userExtensions: [MINE, MINE_OFF], query: "state=enabled" });

    expect(privateRows(w).map((r) => r.find("h3").text())).toEqual(["My notes"]);
  });

  it("opens the add form from the button and the edit form from a row", async () => {
    const { w } = await show({ userExtensions: [MINE] });

    await addButton(w).trigger("click");
    expect(w.getComponent(UserExtensionModal).props("open")).toBe(true);
    expect(w.getComponent(UserExtensionModal).props("extension")).toBeNull();

    await row(w, "My notes").get("button.edit").trigger("click");
    expect(w.getComponent(UserExtensionModal).props("extension")).toMatchObject({ id: "mynotes" });
  });

  it("adds the saved extension to the list and closes the form", async () => {
    mocks.userCreate.mockResolvedValue({ ...MINE, id: "fresh", label: "Fresh" });
    const { w } = await show();
    await addButton(w).trigger("click");

    await w.get("input[name=label]").setValue("Fresh");
    await w.get("input[name=url]").setValue("https://fresh.example.com/mcp");
    await w.get("form.form").trigger("submit");
    await flushPromises();

    expect(names(w)).toContain("Fresh");
    expect(w.getComponent(UserExtensionModal).props("open")).toBe(false);
  });

  it("asks before removing, and removes", async () => {
    mocks.userRemove.mockResolvedValue(undefined);
    const { w } = await show({ userExtensions: [MINE] });

    await row(w, "My notes").get("button.remove").trigger("click");
    expect(w.getComponent(ConfirmModal).props("message")).toContain('Remove "My notes"');
    await w.getComponent(ConfirmModal).get(".confirm").trigger("click");
    await flushPromises();

    expect(mocks.userRemove).toHaveBeenCalledWith("mynotes");
    expect(names(w)).not.toContain("My notes");
  });

  it("refreshes the statuses when the page opens", async () => {
    await show({ userExtensions: [MINE] });

    expect(mocks.userList).toHaveBeenCalledTimes(2); // once at sign-in, once for the page
  });

  it("shows why a change failed", async () => {
    mocks.userUpdate.mockRejectedValue(new Error("offline"));
    const { w } = await show({ userExtensions: [MINE] });

    await row(w, "My notes").get("button.secondary").trigger("click");
    await flushPromises();

    expect(w.get("[role=alert]").text()).toContain("offline");
    expect(row(w, "My notes").find(".added").exists()).toBe(true); // rolled back
  });
});
