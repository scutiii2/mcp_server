import { requestCompletionPermission } from "../composables/useCompletionNotify";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { reactive } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { authClient } from "../api/AuthClient";
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
  browserNotifications: false,
  forceToolApproval: false,
  setCaveman: vi.fn((on: boolean) => (chat.caveman = on)),
  setAskBeforeTools: vi.fn((on: boolean) => (chat.askBeforeTools = on)),
  setChime: vi.fn((on: boolean) => (chat.chime = on)),
  setBrowserNotifications: vi.fn((on: boolean) => (chat.browserNotifications = on)),
  refreshSettings: vi.fn(() => Promise.resolve()),
});
vi.mock("../stores/chat", () => ({ useChatStore: () => chat }));

vi.mock("../composables/useCompletionNotify", () => ({ requestCompletionPermission: vi.fn(async () => "") }));

const client = vi.mocked(settingsClient);

const MEMBER = ["chat.use", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"];
const ADMIN = ["chat.use", "roles.manage", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"];

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
  chat.browserNotifications = false;
  chat.forceToolApproval = false;
  document.documentElement.style.colorScheme = "";
});

describe("SettingsView", () => {
  it("keeps prompt suggestions as a draft until Save, then persists them", async () => {
    const w = await mountView();
    const set = vi
      .spyOn(authClient, "setPreferences")
      .mockResolvedValue({ ...useAuthStore().account!, prompt_suggestions: false });
    expect(row(w, "chat-suggestions").find("button.reset").exists()).toBe(false);

    await row(w, "chat-suggestions").get("input").setValue(false);
    await flushPromises();

    expect(set).not.toHaveBeenCalled();
    expect(useAuthStore().promptSuggestions).toBe(true);
    await w.get("button.save").trigger("click");
    await flushPromises();
    expect(set).toHaveBeenCalledWith({ prompt_suggestions: false });
    expect(useAuthStore().promptSuggestions).toBe(false);
    expect(row(w, "chat-suggestions").find("button.reset").exists()).toBe(true);
  });

  it("resets prompt suggestions to on, which is their default", async () => {
    const w = await mountView();
    useAuthStore().account = { ...useAuthStore().account!, prompt_suggestions: false };
    const set = vi
      .spyOn(authClient, "setPreferences")
      .mockResolvedValue({ ...useAuthStore().account!, prompt_suggestions: true });
    await flushPromises();

    await row(w, "chat-suggestions").get("button.reset").trigger("click");
    await flushPromises();

    expect(set).not.toHaveBeenCalled();
    await w.get("button.save").trigger("click");
    await flushPromises();
    expect(set).toHaveBeenCalledWith({ prompt_suggestions: true });
    expect(useAuthStore().promptSuggestions).toBe(true);
  });

  it("keeps the old value when the server refuses the change", async () => {
    const w = await mountView();
    vi.spyOn(authClient, "setPreferences").mockRejectedValue(new Error("down"));
    vi.spyOn(console, "warn").mockImplementation(() => undefined);

    await row(w, "chat-suggestions").get("input").setValue(false);
    await flushPromises();

    await w.get("button.save").trigger("click");
    await flushPromises();
    expect(useAuthStore().promptSuggestions).toBe(true);
    expect(w.get('[role="alert"]').text()).toContain("down");
    expect((row(w, "chat-suggestions").get("input").element as HTMLInputElement).checked).toBe(false);
  });

  it("lists the chat and appearance settings, grouped, and no administration for a member", async () => {
    const w = await mountView();

    expect(w.findAll("h3").map((h) => h.text())).toEqual(["Chat", "Appearance", "Sidebar"]);
    expect(rowIds(w)).toEqual(["chat-terse", "chat-ask-tools", "chat-chime", "chat-notifications", "chat-suggestions", "appearance-theme", "sidebar-pages"]);
    expect(w.text()).not.toContain("Tool approval");
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

    expect(chat.setCaveman).not.toHaveBeenCalled();
    expect(row(w, "chat-terse").find(".dot").exists()).toBe(true);
    expect(w.get(".badge").text()).toBe("1 modified");

    await row(w, "chat-terse").get("button.reset").trigger("click");

    expect(chat.setCaveman).not.toHaveBeenCalled();
    expect(row(w, "chat-terse").find(".dot").exists()).toBe(false);
    expect(w.find(".badge").exists()).toBe(false);
  });

  it("resets the chime to on, which is its default", async () => {
    chat.chime = false;
    const w = await mountView();
    expect(row(w, "chat-chime").find("button.reset").exists()).toBe(true);

    await row(w, "chat-chime").get("button.reset").trigger("click");

    expect(chat.setChime).not.toHaveBeenCalled();
    expect(w.find(".badge").exists()).toBe(false);
  });

  it("changes the theme and resets it to System", async () => {
    const w = await mountView();
    const light = row(w, "appearance-theme")
      .findAll("button")
      .find((b) => b.text() === "Light")!;

    await light.trigger("click");

    expect(document.documentElement.style.colorScheme).not.toBe("light");
    expect(row(w, "appearance-theme").find(".dot").exists()).toBe(true);

    await row(w, "appearance-theme").get("button.reset").trigger("click");

    expect(document.documentElement.style.colorScheme).not.toBe("light");
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
    expect(scopes[0]!.attributes("title")).toBe("Applied when you save. Stored on this device.");
    expect(scopes[2]!.attributes("title")).toBe("Applied when you save. Stored on your account.");
    expect(w.text()).not.toContain("Applied when you save. Stored on this device.");
  });
});

describe("modified filter", () => {
  it("is a pill that shows only the changed settings, and toggles back", async () => {
    chat.caveman = true;
    const w = await mountView();
    expect(rowIds(w)).toHaveLength(7);
    expect(w.get(".badge").attributes("aria-pressed")).toBe("false");

    await w.get(".badge").trigger("click");

    expect(rowIds(w)).toEqual(["chat-terse"]);
    expect(w.findAll("h3").map((h) => h.text())).toEqual(["Chat"]);
    expect(w.get(".badge").attributes("aria-pressed")).toBe("true");

    await w.get(".badge").trigger("click");
    expect(rowIds(w)).toHaveLength(7);
  });

  it("drops the filter once nothing is modified any more", async () => {
    chat.caveman = true;
    const w = await mountView();
    await w.get(".badge").trigger("click");

    await row(w, "chat-terse").get("button.reset").trigger("click");

    expect(w.find(".badge").exists()).toBe(false);
    expect(rowIds(w)).toHaveLength(7);
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


  it("says nothing matches, and Clear search brings everything back", async () => {
    const w = await mountView();

    await search(w).setValue("zzz");

    expect(w.text()).toContain('No settings match "zzz"');
    expect(rowIds(w)).toEqual([]);
    await w.get("button.link").trigger("click");
    expect(rowIds(w)).toHaveLength(7);
    expect((search(w).element as HTMLInputElement).value).toBe("");
  });

  it("Enter focuses the first setting that is left, Escape clears the search", async () => {
    const w = await mountView();
    await search(w).setValue("chime");

    await search(w).trigger("keydown", { key: "Enter" });
    expect(document.activeElement).toBe(row(w, "chat-chime").get("input").element);

    await search(w).trigger("keydown", { key: "Escape" });
    expect((search(w).element as HTMLInputElement).value).toBe("");
    expect(rowIds(w)).toHaveLength(7);
  });
});

it("keeps workspace tool approval in Ember Admin", async () => {
  const w = await mountView(ADMIN);
  expect(w.text()).not.toContain("Tool approval");
  expect(w.text()).not.toContain("Applies to all accounts");
  expect(rowIds(w)).toHaveLength(7);
});

it("reverts chat, theme and sidebar drafts without persisting anything", async () => {
  const w = await mountView();
  await row(w, "chat-terse").get("input").setValue(true);
  await row(w, "appearance-theme").findAll("button").find(b => b.text() === "Dark")!.trigger("click");
  await w.get('button[aria-label="Pin Chat to the top"]').trigger("click");
  expect(vi.mocked(navPreferencesClient.save)).not.toHaveBeenCalled();
  expect(chat.caveman).toBe(false);
  await w.get("button.revert").trigger("click");
  expect(w.find(".settings-save-bar").exists()).toBe(false);
  expect((row(w, "chat-terse").get("input").element as HTMLInputElement).checked).toBe(false);
  expect(w.find(".tag").exists()).toBe(false);
});

it("saves local preferences and sidebar edits together", async () => {
  const w = await mountView();
  vi.mocked(navPreferencesClient.save).mockImplementation(async prefs => prefs);
  await row(w, "chat-terse").get("input").setValue(true);
  await row(w, "appearance-theme").findAll("button").find(b => b.text() === "Dark")!.trigger("click");
  await w.get('button[aria-label="Pin Chat to the top"]').trigger("click");
  await w.get("button.save").trigger("click");
  await flushPromises();
  expect(chat.setCaveman).toHaveBeenCalledWith(true);
  expect(document.documentElement.style.colorScheme).toBe("dark");
  expect(navPreferencesClient.save).toHaveBeenCalledWith(expect.objectContaining({ pinned: ["/"] }));
  expect(w.find(".settings-save-bar").exists()).toBe(false);
});

it("keeps unsaved settings after a sidebar save fails, and supports retry", async () => {
  const w = await mountView();
  vi.mocked(navPreferencesClient.save).mockRejectedValueOnce(new Error("Sidebar unavailable")).mockImplementation(async prefs => prefs);
  await w.get('button[aria-label="Pin Chat to the top"]').trigger("click");
  await row(w, "chat-terse").get("input").setValue(true);
  await w.get("button.save").trigger("click");
  await flushPromises();
  expect(w.get('[role="alert"]').text()).toBe("Sidebar unavailable");
  expect(chat.setCaveman).not.toHaveBeenCalled();
  await w.get("button.save").trigger("click");
  await flushPromises();
  expect(w.find(".settings-save-bar").exists()).toBe(false);
  expect(chat.setCaveman).toHaveBeenCalledWith(true);
});

it("requests notification permission on enabling and persists only on Save", async () => {
  const w = await mountView();
  await row(w, "chat-notifications").get("input").setValue(true);
  await flushPromises();
  expect(requestCompletionPermission).toHaveBeenCalledOnce();
  expect(chat.browserNotifications).toBe(false);
  await w.get("button.save").trigger("click");
  await flushPromises();
  expect(chat.setBrowserNotifications).toHaveBeenCalledWith(true);
});
it("explains blocked notifications and leaves the setting off", async () => {
  vi.mocked(requestCompletionPermission).mockResolvedValueOnce("Notifications are blocked.");
  const w = await mountView();
  await row(w, "chat-notifications").get("input").setValue(true);
  await flushPromises();
  expect(w.get('[role="status"]').text()).toBe("Notifications are blocked.");
  expect((row(w, "chat-notifications").get("input").element as HTMLInputElement).checked).toBe(false);
  expect(chat.setBrowserNotifications).not.toHaveBeenCalled();
});
