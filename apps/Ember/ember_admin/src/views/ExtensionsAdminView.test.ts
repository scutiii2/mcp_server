import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { extensionsClient, type ExtensionInfo } from "../api/ExtensionsClient";
import ExtensionsAdminView from "./ExtensionsAdminView.vue";

const NOTES: ExtensionInfo = { id: "notes", label: "Notes", description: "", status: "connected", error: null, tools: ["notes__add"], web_url: null };
const WIKI: ExtensionInfo = { id: "wiki", label: "Wiki", description: "", status: "error", error: "connection refused", tools: [] };

// jsdom has no <dialog> methods.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

beforeEach(() => {
  vi.spyOn(extensionsClient, "list").mockResolvedValue([NOTES, WIKI]);
});
afterEach(() => vi.restoreAllMocks());

async function mounted() {
  const wrapper = mount(ExtensionsAdminView, { attachTo: document.body, global: { plugins: [createPinia()] } });
  await flushPromises();
  return wrapper;
}

describe("ExtensionsAdminView", () => {
  it("lists extensions with their status and error", async () => {
    const wrapper = await mounted();
    expect(wrapper.findAll("[data-test=extension]")).toHaveLength(2);
    expect(wrapper.find("[data-id=wiki]").text()).toContain("connection refused");
  });

  it("adds an extension and shows it", async () => {
    const add = vi.spyOn(extensionsClient, "add").mockResolvedValue({ ...WIKI, id: "docs", label: "Docs" });
    const wrapper = await mounted();

    await wrapper.find("[data-test=label]").setValue("Docs");
    await wrapper.find("[data-test=url]").setValue("http://docs.internal/mcp");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(add).toHaveBeenCalledWith({ label: "Docs", url: "http://docs.internal/mcp", description: "" });
    expect(wrapper.find("[data-id=docs]").exists()).toBe(true);
  });

  it("removes an extension only after the confirm", async () => {
    const remove = vi.spyOn(extensionsClient, "remove").mockResolvedValue(undefined);
    const wrapper = await mounted();

    await wrapper.find("[data-id=notes] [data-test=remove]").trigger("click");
    expect(remove).not.toHaveBeenCalled();
    await wrapper.findComponent({ name: "ConfirmModal" }).vm.$emit("confirm");
    await flushPromises();

    expect(remove).toHaveBeenCalledWith("notes");
    expect(wrapper.find("[data-id=notes]").exists()).toBe(false);
  });

  it("shows the server's message when adding fails", async () => {
    vi.spyOn(extensionsClient, "add").mockRejectedValue(new Error("must be an http:// or https:// URL"));
    const wrapper = await mounted();

    await wrapper.find("[data-test=label]").setValue("Bad");
    await wrapper.find("[data-test=url]").setValue("ftp://x");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(wrapper.find("[data-test=add-error]").text()).toContain("must be an http");
    expect(wrapper.findAll("[data-test=extension]")).toHaveLength(2);
  });

  it("keeps the row and the open modal, showing the error, when a remove fails", async () => {
    vi.spyOn(extensionsClient, "remove").mockRejectedValue(new Error("mcp_server is unreachable"));
    const wrapper = await mounted();

    await wrapper.find("[data-id=notes] [data-test=remove]").trigger("click");
    const modal = wrapper.findComponent({ name: "ConfirmModal" });
    await modal.vm.$emit("confirm");
    await flushPromises();

    expect(wrapper.find("[data-id=notes]").exists()).toBe(true);
    expect(modal.props("open")).toBe(true);
    expect(modal.props("message")).toContain("mcp_server is unreachable");
    expect(modal.text()).toContain("mcp_server is unreachable");
  });

  it("marks the modal busy while a remove is pending", async () => {
    let finish!: () => void;
    vi.spyOn(extensionsClient, "remove").mockReturnValue(new Promise<void>((r) => (finish = r)));
    const wrapper = await mounted();

    await wrapper.find("[data-id=notes] [data-test=remove]").trigger("click");
    const modal = wrapper.findComponent({ name: "ConfirmModal" });
    await modal.vm.$emit("confirm");
    expect(modal.props("busy")).toBe(true);
    expect(wrapper.find("[data-id=notes]").exists()).toBe(true);

    finish();
    await flushPromises();
    expect(modal.props("busy")).toBe(false);
    expect(wrapper.find("[data-id=notes]").exists()).toBe(false);
  });

  it("gives the add form inputs accessible names", async () => {
    const wrapper = await mounted();
    expect(wrapper.find('input[aria-label="Name"]').attributes("data-test")).toBe("label");
    expect(wrapper.find('input[aria-label="URL"]').attributes("data-test")).toBe("url");
    expect(wrapper.find('input[aria-label="Description"]').exists()).toBe(true);
  });

  it("works for an empty list", async () => {
    vi.spyOn(extensionsClient, "list").mockResolvedValue([]);
    const wrapper = await mounted();
    expect(wrapper.findAll("[data-test=extension]")).toHaveLength(0);
    expect(wrapper.find("form").exists()).toBe(true);
  });
});

it("searches extension names and their tool names", async () => {
  const wrapper = await mounted();
  const search = wrapper.get('input[aria-label="Search extensions"]');
  await search.setValue(" NOTES__ADD ");
  expect(wrapper.findAll("[data-test=extension]")).toHaveLength(1);
  expect(wrapper.get("[data-test=extension]").attributes("data-id")).toBe("notes");
  await search.setValue("wiki");
  expect(wrapper.get("[data-test=extension]").attributes("data-id")).toBe("wiki");
  await search.setValue("no match");
  expect(wrapper.text()).toContain("No extensions match your search.");
  await search.setValue("");
  expect(wrapper.findAll("[data-test=extension]")).toHaveLength(2);
});
