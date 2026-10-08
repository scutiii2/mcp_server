import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Account } from "../api/AuthClient";
import { navPreferencesClient, type NavPrefs } from "../api/NavPreferencesClient";
import { useAuthStore } from "../stores/auth";
import SidebarEditor from "./SidebarEditor.vue";

vi.mock("../api/NavPreferencesClient", () => ({
  navPreferencesClient: { get: vi.fn(), save: vi.fn(), reset: vi.fn() },
}));

const ACCOUNT: Account = { id: 1, username: "lex", email: "l@e.com", email_verified: true, roles: [], permissions: ["chat.use", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"] };
// chat.use opens: Chat, Capabilities, Agents, Usage, Settings (in that default order).
const DEFAULT_ORDER = ["Chat", "Capabilities", "Agents", "Usage", "Settings"];
const EMPTY: NavPrefs = { order: [], pinned: [], hidden: [] };

async function setup(stored: NavPrefs = EMPTY) {
  vi.mocked(navPreferencesClient.get).mockResolvedValue(stored);
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().account = ACCOUNT;
  const wrapper = mount(SidebarEditor, { global: { plugins: [pinia] } });
  await flushPromises();
  return wrapper;
}

const names = (wrapper: Awaited<ReturnType<typeof setup>>) => wrapper.findAll(".row .name").map((n) => n.text());
const row = (wrapper: Awaited<ReturnType<typeof setup>>, label: string) =>
  wrapper.findAll(".row").find((r) => r.find(".name").text() === label)!;
const lastSaved = () => vi.mocked(navPreferencesClient.save).mock.lastCall![0];

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(navPreferencesClient.save).mockImplementation(async (p) => p);
  vi.mocked(navPreferencesClient.reset).mockResolvedValue(undefined);
});

describe("SidebarEditor", () => {
  it("lists the pages the account may open in the default order", async () => {
    expect(names(await setup())).toEqual(DEFAULT_ORDER);
  });

  it("lists pinned pages first and marks them", async () => {
    const wrapper = await setup({ order: [], pinned: ["/usage"], hidden: [] });

    expect(names(wrapper).slice(0, 2)).toEqual(["Usage", "Chat"]);
    expect(row(wrapper, "Usage").find(".tag").exists()).toBe(true);
  });

  it("moves a page down with its arrow and saves the order", async () => {
    const wrapper = await setup();

    await row(wrapper, "Chat").find('button[aria-label="Move Chat down"]').trigger("click");
    await flushPromises();

    expect(names(wrapper)).toEqual(["Capabilities", "Chat", "Agents", "Usage", "Settings"]);
    expect(lastSaved().order.slice(0, 2)).toEqual(["/capabilities", "/"]);
  });

  it("disables the arrows at the ends of a group", async () => {
    const wrapper = await setup();

    expect(row(wrapper, "Chat").find('button[aria-label="Move Chat up"]').attributes("disabled")).toBeDefined();
    expect(row(wrapper, "Settings").find('button[aria-label="Move Settings down"]').attributes("disabled")).toBeDefined();
  });

  it("reorders by dragging one row onto another", async () => {
    const wrapper = await setup();

    await row(wrapper, "Settings").trigger("dragstart");
    await row(wrapper, "Chat").trigger("drop");
    await flushPromises();

    expect(names(wrapper)).toEqual(["Settings", "Chat", "Capabilities", "Agents", "Usage"]);
  });

  it("shows a drop slot after the hovered row when moving down and before it when moving up", async () => {
    const wrapper = await setup();
    const order = () => wrapper.findAll(".rows > li").map((li) => (li.classes("slot") ? "slot" : li.find(".name").text()));

    await row(wrapper, "Chat").trigger("dragstart");
    await row(wrapper, "Agents").trigger("dragover");
    expect(order()).toEqual(["Chat", "Capabilities", "Agents", "slot", "Usage", "Settings"]);

    await row(wrapper, "Chat").trigger("dragend");
    await row(wrapper, "Settings").trigger("dragstart");
    await row(wrapper, "Capabilities").trigger("dragover");
    expect(order()).toEqual(["Chat", "slot", "Capabilities", "Agents", "Usage", "Settings"]);
  });

  it("shows no slot over the dragged row, after a drop or after the drag ends", async () => {
    const wrapper = await setup();

    await row(wrapper, "Chat").trigger("dragstart");
    await row(wrapper, "Chat").trigger("dragover");
    expect(wrapper.find(".slot").exists()).toBe(false);

    await row(wrapper, "Agents").trigger("dragover");
    expect(wrapper.find(".slot").exists()).toBe(true);
    await row(wrapper, "Agents").trigger("dragend");
    expect(wrapper.find(".slot").exists()).toBe(false);
  });

  it("drops onto the slot as onto its row", async () => {
    const wrapper = await setup();

    await row(wrapper, "Chat").trigger("dragstart");
    await row(wrapper, "Agents").trigger("dragover");
    await wrapper.find(".slot").trigger("drop");
    await flushPromises();

    expect(names(wrapper)).toEqual(["Capabilities", "Agents", "Chat", "Usage", "Settings"]);
  });

  it("pins and unpins a page", async () => {
    const wrapper = await setup();

    await row(wrapper, "Usage").find('button[aria-pressed]').trigger("click");
    await flushPromises();
    expect(lastSaved().pinned).toEqual(["/usage"]);
    expect(names(wrapper)[0]).toBe("Usage");

    await row(wrapper, "Usage").find('button[aria-pressed]').trigger("click");
    await flushPromises();
    expect(lastSaved().pinned).toEqual([]);
  });

  it("hides a page with its switch, dimming the row", async () => {
    const wrapper = await setup();

    await row(wrapper, "Agents").find('input[role="switch"]').setValue(false);
    await flushPromises();

    expect(lastSaved().hidden).toEqual(["/agents"]);
    expect(row(wrapper, "Agents").classes()).toContain("off");
  });

  it("offers a reset only when the arrangement differs from the default", async () => {
    const plain = await setup();
    expect(plain.find("button.reset").exists()).toBe(false);

    const changed = await setup({ order: [], pinned: [], hidden: ["/agents"] });
    await changed.find("button.reset").trigger("click");
    await flushPromises();

    expect(navPreferencesClient.reset).toHaveBeenCalled();
    expect(names(changed)).toEqual(DEFAULT_ORDER);
  });

  it("shows why a save failed", async () => {
    const wrapper = await setup();
    vi.mocked(navPreferencesClient.save).mockRejectedValue(new Error("Server is down"));

    await row(wrapper, "Agents").find('input[role="switch"]').setValue(false);
    await flushPromises();

    expect(wrapper.find('[role="alert"]').text()).toBe("Server is down");
  });
});
