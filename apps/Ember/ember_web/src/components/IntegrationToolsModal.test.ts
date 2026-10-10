import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { commandsClient } from "../api/CommandsClient";
import { useAuthStore } from "../stores/auth";
import IntegrationToolsModal from "./IntegrationToolsModal.vue";

const TOOL = { name: "notes_add", title: "Add note", description: "Create a note", inputSchema: { type: "object", properties: {} } };
const EXT_TOOL = { ...TOOL, name: "ext__run", title: "Run" };
beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close ??= function () { this.removeAttribute("open"); };
});
beforeEach(() => {
  setActivePinia(createPinia());
  useAuthStore().account = { id: 1, username: "u", email: "u@example.com", email_verified: true, roles: [], permissions: ["tools.view", "tools.execute"] } as never;
});

describe("IntegrationToolsModal slash commands", () => {
  it("shows the command of a built-in tool", async () => {
    vi.spyOn(commandsClient, "list").mockResolvedValue([{ capability: "notes", name: "add", description: "", tool_name: TOOL.name }]);
    const wrapper = mount(IntegrationToolsModal, { props: { open: true, title: "Notes", identity: "notes", names: [TOOL.name], available: true, providedTools: [TOOL] as never } });
    await flushPromises();
    expect(wrapper.find(".cmd-badge").exists()).toBe(true);
    await wrapper.get(".tool-list button").trigger("click");
    expect(wrapper.get(".tool-command code").text()).toBe("/notes add");
  });
  it("derives the command of a shared extension tool, not a private one", async () => {
    vi.spyOn(commandsClient, "list").mockResolvedValue([]);
    const shared = mount(IntegrationToolsModal, { props: { open: true, title: "Ext", identity: "ext", kind: "extension", names: [EXT_TOOL.name], available: true, providedTools: [EXT_TOOL] as never } });
    await flushPromises();
    await shared.get(".tool-list button").trigger("click");
    expect(shared.get(".tool-command code").text()).toBe("/ext run");
    const priv = mount(IntegrationToolsModal, { props: { open: true, title: "Ext", identity: "ext", kind: "extension", privateExtension: true, names: [EXT_TOOL.name], available: true, providedTools: [EXT_TOOL] as never } });
    await flushPromises();
    expect(priv.find(".cmd-badge").exists()).toBe(false);
  });
});
