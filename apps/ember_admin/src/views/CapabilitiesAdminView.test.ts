import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { capabilitiesAdminClient, type CapabilityStatus } from "../api/CapabilitiesAdminClient";
import { commandsClient } from "../api/CommandsClient";
import CapabilitiesAdminView from "./CapabilitiesAdminView.vue";

function cap(over: Partial<CapabilityStatus>): CapabilityStatus {
  return { name: "vault", enabled: true, label: "Vault", tools: ["tool_vault_search"], resources: [], has_gui: false, load_error: null, missing: false, loaded: true, ...over };
}

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close ??= function () { this.removeAttribute("open"); };
});
beforeEach(() => {
  vi.spyOn(commandsClient, "helpIndex").mockResolvedValue({ capabilities: [{ capability: "/vault", summary: "Search and manage notes in your vault." }] });
  vi.spyOn(capabilitiesAdminClient, "list").mockResolvedValue([
    cap({}),
    cap({ name: "fresh", label: "Fresh", enabled: false, loaded: false, tools: [] }),
    cap({ name: "broken", label: "Broken", enabled: false, load_error: "RuntimeError: boom" }),
    cap({ name: "gone", label: "Gone", enabled: false, missing: true }),
  ]);
});
afterEach(() => vi.restoreAllMocks());

async function mounted() {
  const wrapper = mount(CapabilitiesAdminView, { global: { plugins: [createPinia()] } });
  await flushPromises();
  return wrapper;
}

describe("CapabilitiesAdminView", () => {
  it("shows each capability with its state", async () => {
    const wrapper = await mounted();
    const rows = wrapper.findAll("[data-test=capability]");
    expect(rows.map((r) => r.attributes("data-state"))).toEqual(["online", "new", "error", "missing"]);
  });

  it("shows the load error text on the row", async () => {
    const wrapper = await mounted();
    expect(wrapper.find("[data-name=broken] [data-test=load-error]").text()).toContain("RuntimeError: boom");
  });

  it("brings a capability online and waits for the server before showing it", async () => {
    // A deferred answer: an instantly resolved mock would clear the pending state before the first assertion.
    let answer: (value: CapabilityStatus) => void = () => {};
    const set = vi.spyOn(capabilitiesAdminClient, "setOnline").mockReturnValue(new Promise((resolve) => (answer = resolve)));
    const wrapper = await mounted();
    const toggle = wrapper.find("[data-name=fresh] input[type=checkbox]");

    await toggle.setValue(true);
    expect(set).toHaveBeenCalledWith("fresh", true);
    expect((toggle.element as HTMLInputElement).disabled).toBe(true); // pending
    expect((toggle.element as HTMLInputElement).checked).toBe(false); // not shown until the server confirms
    expect(wrapper.find("[data-name=fresh]").attributes("data-state")).toBe("new");
    answer(cap({ name: "fresh", enabled: true, loaded: true }));
    await flushPromises();
    expect((toggle.element as HTMLInputElement).checked).toBe(true);

    expect(wrapper.find("[data-name=fresh]").attributes("data-state")).toBe("online");
  });

  it("keeps a capability offline and shows the error when going online fails", async () => {
    vi.spyOn(capabilitiesAdminClient, "setOnline").mockRejectedValue(new Error("boom in tool.py"));
    const wrapper = await mounted();

    await wrapper.find("[data-name=fresh] input[type=checkbox]").setValue(true);
    await flushPromises();

    expect(wrapper.find("[data-name=fresh]").attributes("data-state")).not.toBe("online");
    expect(wrapper.find("[data-name=fresh] [data-test=row-error]").text()).toContain("boom in tool.py");
  });

  it("refresh reloads the list", async () => {
    const refresh = vi.spyOn(capabilitiesAdminClient, "refresh").mockResolvedValue([cap({}), cap({ name: "newest", label: "Newest", enabled: false, loaded: false })]);
    const wrapper = await mounted();

    await wrapper.find("[data-test=refresh]").trigger("click");
    await flushPromises();

    expect(refresh).toHaveBeenCalled();
    expect(wrapper.findAll("[data-test=capability]")).toHaveLength(2);
  });

  it("cannot bring a missing capability online", async () => {
    const wrapper = await mounted();
    expect((wrapper.find("[data-name=gone] input[type=checkbox]").element as HTMLInputElement).disabled).toBe(true);
  });

  it("can switch off a missing capability that is still online", async () => {
    vi.mocked(capabilitiesAdminClient.list).mockResolvedValue([cap({ name: "gone", label: "Gone", enabled: true, missing: true })]);
    const set = vi.spyOn(capabilitiesAdminClient, "setOnline").mockResolvedValue(cap({ name: "gone", enabled: false, missing: true }));
    const wrapper = await mounted();
    const toggle = wrapper.find("[data-name=gone] input[type=checkbox]");

    expect(wrapper.find("[data-name=gone]").attributes("data-state")).toBe("missing");
    expect((toggle.element as HTMLInputElement).disabled).toBe(false);
    await toggle.setValue(false);

    expect(set).toHaveBeenCalledWith("gone", false);
  });
});

it("shows the capability summary beneath its metadata, with a fallback if help is unavailable", async () => {
  const wrapper = await mounted();
  await wrapper.get('button[aria-label="Open Vault"]').trigger("click");
  await flushPromises();
  expect(wrapper.get(".summary-description").text()).toContain("Search and manage notes in your vault.");
  vi.mocked(commandsClient.helpIndex).mockRejectedValue(new Error("Unavailable"));
  await wrapper.get('button[aria-label="Open Fresh"]').trigger("click");
  await flushPromises();
  expect(wrapper.get(".summary-description").text()).toContain("Workspace tools provided by Fresh.");
});

it("searches capability labels and tool names without changing their state", async () => {
  const wrapper = await mounted();
  const search = wrapper.get('input[aria-label="Search capabilities"]');
  await search.setValue("  VAULT_SEARCH  ");
  expect(wrapper.findAll("[data-test=capability]")).toHaveLength(3);
  await search.setValue("Fresh");
  expect(wrapper.findAll("[data-test=capability]")).toHaveLength(1);
  expect(wrapper.get("[data-test=capability]").attributes("data-name")).toBe("fresh");
  await search.setValue("no match");
  expect(wrapper.text()).toContain("No capabilities match your search.");
  await search.setValue("");
  expect(wrapper.findAll("[data-test=capability]")).toHaveLength(4);
});
