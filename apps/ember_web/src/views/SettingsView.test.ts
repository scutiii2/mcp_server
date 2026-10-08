import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { reactive } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { navPreferencesClient } from "../api/NavPreferencesClient";
import { settingsClient } from "../api/SettingsClient";
import { useAuthStore } from "../stores/auth";
import SettingsView from "./SettingsView.vue";

vi.mock("../api/SettingsClient", () => ({ settingsClient: { get: vi.fn(), set: vi.fn() } }));
vi.mock("../api/NavPreferencesClient", () => ({
  navPreferencesClient: { get: vi.fn(), save: vi.fn(), reset: vi.fn() },
}));

// The chat store is big and talks to ember_api; this page only reads and sets
// four preferences on it, so a plain stand-in is enough.
const chat = reactive({
  caveman: false,
  askBeforeTools: false,
  chime: true,
  forceToolApproval: false,
  setCaveman: vi.fn((on: boolean) => (chat.caveman = on)),
  setAskBeforeTools: vi.fn((on: boolean) => (chat.askBeforeTools = on)),
  setChime: vi.fn((on: boolean) => (chat.chime = on)),
  refreshSettings: vi.fn(() => Promise.resolve()),
});
vi.mock("../stores/chat", () => ({ useChatStore: () => chat }));

const client = vi.mocked(settingsClient);

const MEMBER = ["chat.use"];
const ADMIN = ["chat.use", "admin.manage"];

async function mountView(permissions: string[] = MEMBER, forced = false) {
  setActivePinia(createPinia());
  useAuthStore().account = {
    id: 1,
    username: "ada",
    email: "ada@example.com",
    email_verified: true,
    roles: [],
    permissions,
  };
  client.get.mockResolvedValue({ force_tool_approval: forced });
  vi.mocked(navPreferencesClient.get).mockResolvedValue({ order: [], pinned: [], hidden: [] });
  const wrapper = mount(SettingsView, { attachTo: document.body });
  await flushPromises();
  return wrapper;
}

const rowIds = (w: Awaited<ReturnType<typeof mountView>>) =>
  w.findAll("[data-setting-id]").map((r) => r.attributes("data-setting-id"));
const row = (w: Awaited<ReturnType<typeof mountView>>, id: string) => w.get(`[data-setting-id="${id}"]`);
const search = (w: Awaited<ReturnType<typeof mountView>>) => w.get("input.search");

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  document.body.innerHTML = "";
  chat.caveman = false;
  chat.askBeforeTools = false;
  chat.chime = true;
  chat.forceToolApproval = false;
  document.documentElement.style.colorScheme = "";
});

describe("SettingsView", () => {
  it("lists the chat and appearance settings, grouped, and no administration for a member", async () => {
    const w = await mountView();

    expect(w.findAll("h3").map((h) => h.text())).toEqual(["Chat", "Appearance", "Sidebar"]);
    expect(rowIds(w)).toEqual(["chat-terse", "chat-ask-tools", "chat-chime", "appearance-theme", "sidebar-pages"]);
    expect(w.text()).not.toContain("Tool approval");
  });

  it("shows the tool approval setting to an administrator", async () => {
    const w = await mountView(ADMIN);

    expect(w.text()).toContain("Tool approval");
    expect(w.text()).toContain("Applies to all accounts");
  });

  it("shows no modified badge, dot or reset while everything is at its default", async () => {
    const w = await mountView();

    expect(w.find(".badge").exists()).toBe(false);
    expect(w.find(".dot").exists()).toBe(false);
    expect(w.find("button.reset").exists()).toBe(false);
  });

  it("marks a changed switch, counts it, and puts it back with its reset", async () => {
    const w = await mountView();

    await row(w, "chat-terse").get("input").setValue(true);

    expect(chat.setCaveman).toHaveBeenCalledWith(true);
    expect(row(w, "chat-terse").find(".dot").exists()).toBe(true);
    expect(w.get(".badge").text()).toBe("1 modified");

    await row(w, "chat-terse").get("button.reset").trigger("click");

    expect(chat.setCaveman).toHaveBeenLastCalledWith(false);
    expect(row(w, "chat-terse").find(".dot").exists()).toBe(false);
    expect(w.find(".badge").exists()).toBe(false);
  });

  it("resets the chime to on, which is its default", async () => {
    chat.chime = false;
    const w = await mountView();
    expect(row(w, "chat-chime").find("button.reset").exists()).toBe(true);

    await row(w, "chat-chime").get("button.reset").trigger("click");

    expect(chat.setChime).toHaveBeenCalledWith(true);
    expect(w.find(".badge").exists()).toBe(false);
  });

  it("changes the theme and resets it to System", async () => {
    const w = await mountView();
    const light = row(w, "appearance-theme")
      .findAll("button")
      .find((b) => b.text() === "Light")!;

    await light.trigger("click");

    expect(document.documentElement.style.colorScheme).toBe("light");
    expect(row(w, "appearance-theme").find(".dot").exists()).toBe(true);

    await row(w, "appearance-theme").get("button.reset").trigger("click");

    expect(document.documentElement.style.colorScheme).toBe("light dark");
    expect(row(w, "appearance-theme").find(".dot").exists()).toBe(false);
  });

  it("locks Ask before tools, and says why, while an administrator forces approval", async () => {
    const w = await mountView(MEMBER, true);
    chat.forceToolApproval = true;
    await flushPromises();

    const box = row(w, "chat-ask-tools").get("input").element as HTMLInputElement;
    expect(box.disabled).toBe(true);
    expect(box.checked).toBe(true);
    expect(row(w, "chat-ask-tools").text()).toContain("Your administrator requires approval");
    expect(row(w, "chat-ask-tools").find("button.reset").exists()).toBe(false);
  });

  it("counts the stored tool approval setting for an administrator", async () => {
    const w = await mountView(ADMIN, true);

    expect(w.get(".badge").text()).toBe("1 modified");
  });

  it("re-reads what the administrator requires when it opens", async () => {
    await mountView();

    expect(chat.refreshSettings).toHaveBeenCalledOnce();
  });
});

describe("group headers", () => {
  it("name where the settings live, with the full note as a tooltip", async () => {
    const w = await mountView();

    const scopes = w.findAll(".scope");
    expect(scopes.map((c) => c.text())).toEqual(["This device", "This device", "Your account"]);
    expect(scopes[0]!.attributes("title")).toBe("Applies instantly. Saved on this device.");
    expect(scopes[2]!.attributes("title")).toBe("Applies instantly. Saved to your account.");
    expect(w.text()).not.toContain("Applies instantly. Saved on this device.");
  });
});

describe("modified filter", () => {
  it("is a pill that shows only the changed settings, and toggles back", async () => {
    chat.caveman = true;
    const w = await mountView();
    expect(rowIds(w)).toHaveLength(5);
    expect(w.get(".badge").attributes("aria-pressed")).toBe("false");

    await w.get(".badge").trigger("click");

    expect(rowIds(w)).toEqual(["chat-terse"]);
    expect(w.findAll("h3").map((h) => h.text())).toEqual(["Chat"]);
    expect(w.get(".badge").attributes("aria-pressed")).toBe("true");

    await w.get(".badge").trigger("click");
    expect(rowIds(w)).toHaveLength(5);
  });

  it("drops the filter once nothing is modified any more", async () => {
    chat.caveman = true;
    const w = await mountView();
    await w.get(".badge").trigger("click");

    await row(w, "chat-terse").get("button.reset").trigger("click");

    expect(w.find(".badge").exists()).toBe(false);
    expect(rowIds(w)).toHaveLength(5);
  });
});

describe("search", () => {
  it("filters the settings as you type, hiding a group with no match", async () => {
    const w = await mountView();

    await search(w).setValue("chime");

    expect(rowIds(w)).toEqual(["chat-chime"]);
    expect(w.findAll("h3").map((h) => h.text())).toEqual(["Chat"]);
  });

  it("finds a setting by a keyword it does not show", async () => {
    const w = await mountView();

    await search(w).setValue("dark mode");

    expect(rowIds(w)).toEqual(["appearance-theme"]);
  });

  it("hides the tool approval card unless it matches", async () => {
    const w = await mountView(ADMIN);
    const card = () => w.get(".admin-card").attributes("style") ?? "";

    expect(card()).not.toContain("display: none");
    await search(w).setValue("chime");
    expect(card()).toContain("display: none");
    await search(w).setValue("lock");
    expect(card()).not.toContain("display: none");
  });

  it("says nothing matches, and Clear search brings everything back", async () => {
    const w = await mountView();

    await search(w).setValue("zzz");

    expect(w.text()).toContain('No settings match "zzz"');
    expect(rowIds(w)).toEqual([]);
    await w.get("button.link").trigger("click");
    expect(rowIds(w)).toHaveLength(5);
    expect((search(w).element as HTMLInputElement).value).toBe("");
  });

  it("Enter focuses the first setting that is left, Escape clears the search", async () => {
    const w = await mountView();
    await search(w).setValue("chime");

    await search(w).trigger("keydown", { key: "Enter" });
    expect(document.activeElement).toBe(row(w, "chat-chime").get("input").element);

    await search(w).trigger("keydown", { key: "Escape" });
    expect((search(w).element as HTMLInputElement).value).toBe("");
    expect(rowIds(w)).toHaveLength(5);
  });
});
