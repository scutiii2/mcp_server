import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { McpServerClient } from "../api/McpServerClient";
import { useAuthStore } from "../stores/auth";
import IntegrationToolsModal from "./IntegrationToolsModal.vue";

const TOOL = { name: "notes__add", title: "Add note", description: "Create a note", inputSchema: { type: "object", properties: { text: { type: "string", title: "Text" } }, required: ["text"] } };
beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close ??= function () { this.removeAttribute("open"); };
});
beforeEach(() => {
  setActivePinia(createPinia());
  useAuthStore().account = { id: 1, username: "admin", email: "admin@example.com", email_verified: true, roles: [], permissions: ["extensions.manage", "tools.view", "tools.execute"] };
  vi.spyOn(McpServerClient.prototype, "listTools").mockResolvedValue([TOOL, { ...TOOL, name: "another__add" }]);
});
async function setup(available = true) {
  const wrapper = mount(IntegrationToolsModal, { props: { open: true, title: "Notes", identity: "notes", names: [TOOL.name], available } });
  await flushPromises();
  return wrapper;
}
describe("IntegrationToolsModal", () => {
  it("lists only this integration's tools and runs the selected tool with form arguments", async () => {
    const run = vi.spyOn(McpServerClient.prototype, "runTool").mockResolvedValue({ text: "Created", isError: false });
    const wrapper = await setup();
    expect(wrapper.findAll(".tool-list button")).toHaveLength(1);
    expect(wrapper.text()).not.toContain("another__add");
    await wrapper.get(".tool-list button").trigger("click");
    await wrapper.get(".tool-form input").setValue("Hello");
    await wrapper.get(".tool-form").trigger("submit");
    await flushPromises();
    expect(run).toHaveBeenCalledWith(TOOL.name, { text: "Hello" });
    expect(wrapper.get(".result").text()).toContain("Created");
  });
  it("shows transport and tool errors in the result", async () => {
    vi.spyOn(McpServerClient.prototype, "runTool").mockRejectedValue(new Error("Server unavailable"));
    const wrapper = await setup();
    await wrapper.get(".tool-list button").trigger("click");
    await wrapper.get(".tool-form input").setValue("Hello");
    await wrapper.get(".tool-form").trigger("submit");
    await flushPromises();
    expect(wrapper.get(".result.failed").text()).toContain("Server unavailable");
  });
  it("offers details without execution to a tool viewer", async () => {
    useAuthStore().account!.permissions = ["tools.view"];
    const wrapper = await setup();
    await wrapper.get(".tool-list button").trigger("click");
    expect(wrapper.find(".tool-form").exists()).toBe(false);
    expect(wrapper.text()).toContain("Testing requires Run tools access");
  });
  it("does not query MCP for management-only users or offline integrations", async () => {
    useAuthStore().account!.permissions = ["extensions.manage"];
    const wrapper = await setup();
    expect(McpServerClient.prototype.listTools).not.toHaveBeenCalled();
    expect(wrapper.get(".tool-list button").attributes("disabled")).toBeDefined();
    wrapper.unmount();
    useAuthStore().account!.permissions.push("tools.execute");
    const offline = await setup(false);
    expect(McpServerClient.prototype.listTools).not.toHaveBeenCalled();
    expect(offline.text()).toContain("Bring this capability online");
  });
  it("retains the dialog and blocks duplicate runs while a tool is running", async () => {
    let finish!: (value: { text: string; isError: boolean }) => void;
    const run = vi.spyOn(McpServerClient.prototype, "runTool").mockReturnValue(new Promise((r) => { finish = r; }));
    const wrapper = await setup();
    await wrapper.get(".tool-list button").trigger("click");
    await wrapper.get(".tool-form input").setValue("Hello");
    await wrapper.get(".tool-form").trigger("submit");
    await wrapper.get(".tool-form").trigger("submit");
    await wrapper.get(".close").trigger("click");
    expect(wrapper.emitted("close")).toBeUndefined();
    expect(run).toHaveBeenCalledTimes(1);
    finish({ text: "Done", isError: false });
    await flushPromises();
    expect(wrapper.get(".result").text()).toContain("Done");
  });
});

it("filters tools by name, title, and description", async () => {
  const wrapper = await setup();
  await wrapper.setProps({ names: [TOOL.name, "another__add"] });
  await flushPromises();
  await wrapper.get('input[aria-label="Find a tool"]').setValue("another");
  expect(wrapper.findAll(".tool-list button")).toHaveLength(1);
  expect(wrapper.get(".tool-list").text()).toContain("another__add");
  await wrapper.get('input[aria-label="Find a tool"]').setValue("Create a note");
  expect(wrapper.findAll(".tool-list button")).toHaveLength(2);
  await wrapper.get('input[aria-label="Find a tool"]').setValue("missing");
  expect(wrapper.text()).toContain("No tools match your search.");
});
