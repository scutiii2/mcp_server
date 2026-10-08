import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { templatesClient, type PromptTemplate } from "../api/TemplatesClient";
import { useAuthStore } from "../stores/auth";
import ConfirmModal from "./ConfirmModal.vue";
import TemplatesModal from "./TemplatesModal.vue";

vi.mock("../api/TemplatesClient", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/TemplatesClient")>()),
  templatesClient: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));

const client = vi.mocked(templatesClient);

const tpl = (id: number, name: string, body = `${name} body`): PromptTemplate => ({
  id,
  name,
  body,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
});

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
  client.list.mockResolvedValue([tpl(1, "Summarize"), tpl(2, "Review")]);
  setActivePinia(createPinia());
  useAuthStore().account = { id: 1, username: "u", email: "u@example.com", email_verified: true, roles: [], permissions: ["chat.use", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"] };
});

afterEach(() => {
  document.body.innerHTML = "";
});

type Props = InstanceType<typeof TemplatesModal>["$props"];

/** Mounts closed, then opens, like the chat page does. */
async function openModal(props: Partial<Props> = {}) {
  const wrapper = mount(TemplatesModal, { props: { open: false, draft: "", ...props }, attachTo: document.body });
  await wrapper.setProps({ open: true });
  await flushPromises();
  return wrapper;
}

const errorText = (wrapper: Awaited<ReturnType<typeof openModal>>) => wrapper.find('[role="alert"]').text();

describe("the list", () => {
  it("opens the dialog, loads the prompts and lists them", async () => {
    const wrapper = await openModal();

    expect(wrapper.find("dialog").attributes("open")).toBeDefined();
    expect(client.list).toHaveBeenCalledOnce();
    expect(wrapper.findAll(".list li strong").map((s) => s.text())).toEqual(["Summarize", "Review"]);
    expect(wrapper.find("h3").text()).toBe("Saved prompts");
  });

  it("tells you how to use them when there are none", async () => {
    client.list.mockResolvedValue([]);
    const wrapper = await openModal();

    expect(wrapper.find(".muted").text()).toContain('Type "#"');
  });

  it("shows a load error with a retry", async () => {
    client.list.mockRejectedValueOnce(new Error("down"));
    const wrapper = await openModal();
    expect(errorText(wrapper)).toContain("down");

    await wrapper.find('[role="alert"] button').trigger("click");
    await flushPromises();

    expect(wrapper.findAll(".list li")).toHaveLength(2);
  });

  it("closes the dialog when the parent says so", async () => {
    const wrapper = await openModal();

    await wrapper.setProps({ open: false });
    await flushPromises();

    expect(wrapper.find("dialog").attributes("open")).toBeUndefined();
  });
});

describe("creating", () => {
  it("New prompt opens an empty form; Save is off until both fields are filled", async () => {
    const wrapper = await openModal();

    await wrapper.find("button.primary").trigger("click"); // New prompt
    expect(wrapper.find("h3").text()).toBe("New prompt");
    const save = wrapper.find('form button[type="submit"]');
    expect(save.attributes("disabled")).toBeDefined();

    await wrapper.find('input[type="text"]').setValue("Standup");
    expect(save.attributes("disabled")).toBeDefined();
    await wrapper.find("textarea").setValue("   ");
    expect(save.attributes("disabled")).toBeDefined();
    await wrapper.find("textarea").setValue("What did I do yesterday?");
    expect(save.attributes("disabled")).toBeUndefined();
  });

  it("saves, returns to the list and shows the new prompt first", async () => {
    client.create.mockResolvedValue(tpl(3, "Standup", "What did I do yesterday?"));
    const wrapper = await openModal();
    await wrapper.find("button.primary").trigger("click");
    await wrapper.find('input[type="text"]').setValue("Standup");
    await wrapper.find("textarea").setValue("What did I do yesterday?");

    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(client.create).toHaveBeenCalledWith("Standup", "What did I do yesterday?");
    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.findAll(".list li strong").map((s) => s.text())).toEqual(["Standup", "Summarize", "Review"]);
  });

  it("stays on the form and shows ember_api's message when the name is taken", async () => {
    client.create.mockRejectedValue(new ApiError(409, 'You already have a template named "Review"'));
    const wrapper = await openModal();
    await wrapper.find("button.primary").trigger("click");
    await wrapper.find('input[type="text"]').setValue("Review");
    await wrapper.find("textarea").setValue("x");

    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(errorText(wrapper)).toBe('You already have a template named "Review"');
    expect(wrapper.find("form").exists()).toBe(true);
    expect((wrapper.find("textarea").element as HTMLTextAreaElement).value).toBe("x");
  });

  it("opened with typed text, starts on a new prompt holding it", async () => {
    const wrapper = await openModal({ draft: "Explain this like I am five" });

    expect(wrapper.find("h3").text()).toBe("New prompt");
    expect((wrapper.find("textarea").element as HTMLTextAreaElement).value).toBe("Explain this like I am five");
    expect((wrapper.find('input[type="text"]').element as HTMLInputElement).value).toBe("");
  });

  it("stops the name and text at the limits ember_api enforces", async () => {
    const wrapper = await openModal();
    await wrapper.find("button.primary").trigger("click");

    expect(wrapper.find('input[type="text"]').attributes("maxlength")).toBe("60");
    expect(wrapper.find("textarea").attributes("maxlength")).toBe("10000");
  });
});

describe("editing and deleting", () => {
  it("Edit opens the prompt in the form and Save updates it", async () => {
    client.update.mockResolvedValue(tpl(2, "Code review", "new text"));
    const wrapper = await openModal();

    await wrapper.findAll(".list li")[1]!.findAll("button")[0]!.trigger("click"); // Edit "Review"
    expect(wrapper.find("h3").text()).toBe("Edit prompt");
    expect((wrapper.find('input[type="text"]').element as HTMLInputElement).value).toBe("Review");
    await wrapper.find('input[type="text"]').setValue("Code review");
    await wrapper.find("textarea").setValue("new text");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(client.update).toHaveBeenCalledWith(2, "Code review", "new text");
    expect(wrapper.findAll(".list li strong").map((s) => s.text())).toEqual(["Code review", "Summarize"]);
  });

  it("Cancel goes back to the list without saving", async () => {
    const wrapper = await openModal();
    await wrapper.find("button.primary").trigger("click");
    await wrapper.find('input[type="text"]').setValue("half typed");

    await wrapper.find("button.ghost").trigger("click");

    expect(wrapper.find("form").exists()).toBe(false);
    expect(client.create).not.toHaveBeenCalled();
  });

  it("Delete asks first, then removes", async () => {
    client.remove.mockResolvedValue(undefined);
    const wrapper = await openModal();
    const deleteFirst = () => wrapper.findAll(".list li")[0]!.find("button.danger");

    await deleteFirst().trigger("click");
    expect(client.remove).not.toHaveBeenCalled();
    expect(wrapper.getComponent(ConfirmModal).props("message")).toBe('Delete the prompt "Summarize"?');
    await wrapper.getComponent(ConfirmModal).get(".cancel").trigger("click");
    expect(wrapper.findComponent(ConfirmModal).exists()).toBe(false);
    expect(client.remove).not.toHaveBeenCalled();

    await deleteFirst().trigger("click");
    await wrapper.getComponent(ConfirmModal).get(".confirm").trigger("click");
    await flushPromises();
    expect(client.remove).toHaveBeenCalledWith(1);
    expect(wrapper.findAll(".list li strong").map((s) => s.text())).toEqual(["Review"]);
  });

  it("shows why a delete failed and keeps the prompt", async () => {
    client.remove.mockRejectedValue(new ApiError(500, "database is locked"));
    const wrapper = await openModal();

    await wrapper.findAll(".list li")[0]!.find("button.danger").trigger("click");
    await wrapper.getComponent(ConfirmModal).get(".confirm").trigger("click");
    await flushPromises();

    expect(errorText(wrapper)).toBe("database is locked");
    expect(wrapper.findAll(".list li")).toHaveLength(2);
  });
});

describe("Esc", () => {
  it("steps back from the form to the list first, then closes", async () => {
    const wrapper = await openModal();
    await wrapper.find("button.primary").trigger("click");
    const dialog = wrapper.find("dialog");

    await dialog.trigger("cancel");
    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.emitted("close")).toBeUndefined();

    await dialog.trigger("cancel");
    expect(wrapper.emitted("close")).toHaveLength(1);
  });
});
