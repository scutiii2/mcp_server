import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { sharesClient, type ShareCreated, type ShareInfo } from "../api/SharesClient";
import ConfirmModal from "./ConfirmModal.vue";
import ShareDialog from "./ShareDialog.vue";

vi.mock("../api/SharesClient", () => ({ sharesClient: { create: vi.fn(), list: vi.fn(), revoke: vi.fn(), read: vi.fn() } }));

const client = vi.mocked(sharesClient);

const TOKEN = "T0kenT0kenT0kenT0kenT0kenT0kenT0kenT0kenT0k";

const info = (id: number, extra: Partial<ShareInfo> = {}): ShareInfo => ({
  id,
  chat_id: "chat-1",
  title: "Quarterly report",
  message_count: 3,
  created_at: "2026-01-01T10:00:00",
  expires_at: "2026-01-08T10:00:00",
  ...extra,
});

const created = (id: number, extra: Partial<ShareCreated> = {}): ShareCreated => ({ ...info(id), token: TOKEN, ...extra });

// jsdom has no modal dialogs.
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
  vi.clearAllMocks();
  client.list.mockResolvedValue([]);
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  document.body.innerHTML = "";
});

type Props = InstanceType<typeof ShareDialog>["$props"];

async function openDialog(props: Partial<Props> = {}) {
  const wrapper = mount(ShareDialog, { props: { open: false, chatId: "chat-1", ...props }, attachTo: document.body });
  await wrapper.setProps({ open: true });
  await flushPromises();
  return wrapper;
}

const submit = async (wrapper: Awaited<ReturnType<typeof openDialog>>) => {
  await wrapper.find("form.create").trigger("submit");
  await flushPromises();
};

describe("opening", () => {
  it("opens the dialog and lists this chat's links, without secrets", async () => {
    client.list.mockResolvedValue([info(2), info(1, { expires_at: null, message_count: 5 })]);
    const wrapper = await openDialog();

    expect(wrapper.find("dialog").attributes("open")).toBeDefined();
    expect(client.list).toHaveBeenCalledExactlyOnceWith("chat-1");
    const rows = wrapper.findAll(".links li");
    expect(rows).toHaveLength(2);
    expect(rows[0]!.text()).toContain("3 messages");
    expect(rows[1]!.text()).toContain("never expires");
    expect(rows[1]!.text()).toContain("5 messages");
    expect(wrapper.find(".fresh").exists()).toBe(false);
  });

  it("says when there are none, and that deleting the chat turns links off", async () => {
    const wrapper = await openDialog();

    expect(wrapper.find(".links").exists()).toBe(false);
    expect(wrapper.text()).toContain("None yet.");
    expect(wrapper.text()).toContain("Deleting the chat also turns its links off.");
  });

  it("explains what a link exposes and what it does not", async () => {
    const wrapper = await openDialog();

    const text = wrapper.find(".intro").text();
    expect(text).toContain("read-only copy");
    expect(text).toContain("without logging in");
    expect(text).toContain("tool output");
    expect(text).toContain("Later messages are never added");
  });

  it("shows a failed list load", async () => {
    client.list.mockRejectedValue(new Error("down"));
    const wrapper = await openDialog();

    expect(wrapper.find('[role="alert"]').text()).toBe("down");
  });

  it("closes the dialog when the parent says so, and on Esc asks the parent to", async () => {
    const wrapper = await openDialog();

    await wrapper.find("dialog").trigger("cancel");
    expect(wrapper.emitted("close")).toHaveLength(1);

    await wrapper.setProps({ open: false });
    await flushPromises();
    expect(wrapper.find("dialog").attributes("open")).toBeUndefined();
  });
});

describe("creating a link", () => {
  it("defaults to 7 days and offers 1, 7, 30 and never", async () => {
    const wrapper = await openDialog();

    const options = wrapper.findAll("select option").map((o) => o.text());
    expect(options).toEqual(["1 day", "7 days", "30 days", "Never"]);
    client.create.mockResolvedValue(created(1));
    await submit(wrapper);

    expect(client.create).toHaveBeenCalledExactlyOnceWith("chat-1", 7);
  });

  it.each([
    ["1 day", 1],
    ["30 days", 30],
    ["Never", null],
  ])("passes the chosen expiry: %s", async (label, days) => {
    client.create.mockResolvedValue(created(1));
    const wrapper = await openDialog();
    const options = wrapper.findAll("select option");
    const index = options.findIndex((o) => o.text() === label);

    await wrapper.find("select").setValue((options[index]!.element as HTMLOptionElement).value);
    await submit(wrapper);

    expect(client.create).toHaveBeenCalledWith("chat-1", days);
  });

  it("shows the full link once, with a warning and a copy button", async () => {
    client.create.mockResolvedValue(created(1));
    const wrapper = await openDialog();

    await submit(wrapper);

    const box = wrapper.find(".fresh");
    expect(box.text()).toContain("shown only once");
    const url = `${window.location.origin}/shared/${TOKEN}`;
    expect((box.find("input").element as HTMLInputElement).value).toBe(url);
    expect(box.find("input").attributes("readonly")).toBeDefined();
    expect(box.find('button[aria-label="Copy link"]').exists()).toBe(true);
    expect(wrapper.findAll(".links li")).toHaveLength(1);
    expect(wrapper.find(".links li").text()).toContain("(new)");
    // The list row carries no secret.
    expect(wrapper.find(".links").html()).not.toContain(TOKEN);
  });

  it("puts the new link first in the list", async () => {
    client.list.mockResolvedValue([info(1)]);
    client.create.mockResolvedValue(created(2));
    const wrapper = await openDialog();

    await submit(wrapper);

    expect(wrapper.findAll(".links li")).toHaveLength(2);
    expect(wrapper.findAll(".links li")[0]!.text()).toContain("(new)");
  });

  it("keeps the token out of the link list it holds, not just out of the page", async () => {
    client.create.mockResolvedValue(created(1));
    const wrapper = await openDialog();

    await submit(wrapper);

    const held = (wrapper.vm as unknown as { links: object[] }).links;
    expect(held).toHaveLength(1);
    expect(held[0]).not.toHaveProperty("token");
    expect(JSON.stringify(held)).not.toContain(TOKEN);
  });

  it("never writes the token to browser storage", async () => {
    client.create.mockResolvedValue(created(1));
    const wrapper = await openDialog();

    await submit(wrapper);

    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("forgets the token when the dialog is closed and opened again", async () => {
    client.create.mockResolvedValue(created(1));
    client.list.mockResolvedValue([info(1)]);
    const wrapper = await openDialog();
    await submit(wrapper);
    expect(wrapper.html()).toContain(TOKEN);

    await wrapper.setProps({ open: false });
    await flushPromises();
    await wrapper.setProps({ open: true });
    await flushPromises();

    expect(wrapper.html()).not.toContain(TOKEN);
    expect(wrapper.find(".fresh").exists()).toBe(false);
    expect(wrapper.findAll(".links li")).toHaveLength(1); // still listed, but without a secret
  });

  it("shows ember_api's message when there is nothing to share", async () => {
    client.create.mockRejectedValue(new ApiError(422, "This chat has nothing to share yet"));
    const wrapper = await openDialog();

    await submit(wrapper);

    expect(wrapper.find('[role="alert"]').text()).toBe("This chat has nothing to share yet");
    expect(wrapper.find(".fresh").exists()).toBe(false);
  });

  it("shows the limit message", async () => {
    client.create.mockRejectedValue(new ApiError(409, "At most 50 active shared links per account - revoke some first"));
    const wrapper = await openDialog();

    await submit(wrapper);

    expect(wrapper.find('[role="alert"]').text()).toContain("At most 50");
  });

  it("cannot be double-submitted while it is being made", async () => {
    let finish!: (value: ShareCreated) => void;
    client.create.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const wrapper = await openDialog();

    await wrapper.find("form.create").trigger("submit");
    await wrapper.find("form.create").trigger("submit");
    expect(wrapper.find("button.primary").text()).toBe("Creating …");
    expect(wrapper.find("button.primary").attributes("disabled")).toBeDefined();

    finish(created(1));
    await flushPromises();
    expect(client.create).toHaveBeenCalledOnce();
    expect(wrapper.find("button.primary").text()).toBe("Create link");
  });

  it("is off without a chat", async () => {
    const wrapper = await openDialog({ chatId: null });

    expect(wrapper.find("button.primary").attributes("disabled")).toBeDefined();
    expect(client.list).not.toHaveBeenCalled();
  });

  it("ignores an answer that arrives after the dialog was closed", async () => {
    let finish!: (value: ShareCreated) => void;
    client.create.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const wrapper = await openDialog();
    await wrapper.find("form.create").trigger("submit");

    await wrapper.setProps({ open: false });
    await flushPromises();
    finish(created(1));
    await flushPromises();
    await wrapper.setProps({ open: true });
    await flushPromises();

    expect(wrapper.html()).not.toContain(TOKEN);
  });
});

describe("turning links off", () => {
  it("asks first, then revokes and removes the row", async () => {
    client.list.mockResolvedValue([info(2), info(1)]);
    client.revoke.mockResolvedValue(undefined);
    const wrapper = await openDialog();

    await wrapper.findAll(".links li")[0]!.find("button.danger").trigger("click");
    expect(client.revoke).not.toHaveBeenCalled();
    expect(wrapper.getComponent(ConfirmModal).props("message")).toContain("no longer be able to open");
    await wrapper.getComponent(ConfirmModal).get(".cancel").trigger("click");
    expect(wrapper.findComponent(ConfirmModal).exists()).toBe(false);
    expect(client.revoke).not.toHaveBeenCalled();

    await wrapper.findAll(".links li")[0]!.find("button.danger").trigger("click");
    await wrapper.getComponent(ConfirmModal).get(".confirm").trigger("click");
    await flushPromises();

    expect(client.revoke).toHaveBeenCalledExactlyOnceWith(2);
    expect(wrapper.findAll(".links li")).toHaveLength(1);
  });

  it("removes the just-made link's secret from view when that link is turned off", async () => {
    client.create.mockResolvedValue(created(1));
    client.revoke.mockResolvedValue(undefined);
    const wrapper = await openDialog();
    await submit(wrapper);

    await wrapper.find(".links li button.danger").trigger("click");
    await wrapper.getComponent(ConfirmModal).get(".confirm").trigger("click");
    await flushPromises();

    expect(wrapper.find(".fresh").exists()).toBe(false);
    expect(wrapper.html()).not.toContain(TOKEN);
  });

  it("keeps the row and says why when revoking fails", async () => {
    client.list.mockResolvedValue([info(1)]);
    client.revoke.mockRejectedValue(new ApiError(500, "database is locked"));
    const wrapper = await openDialog();

    await wrapper.find(".links li button.danger").trigger("click");
    await wrapper.getComponent(ConfirmModal).get(".confirm").trigger("click");
    await flushPromises();

    expect(wrapper.find('[role="alert"]').text()).toBe("database is locked");
    expect(wrapper.findAll(".links li")).toHaveLength(1);
  });
});
