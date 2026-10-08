import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { capabilitiesAdminClient, type CapabilityStatus } from "../api/CapabilitiesAdminClient";
import CapabilitiesAdminView from "./CapabilitiesAdminView.vue";

function cap(over: Partial<CapabilityStatus>): CapabilityStatus {
  return { name: "vault", enabled: true, label: "Vault", tools: ["tool_vault_search"], resources: [], has_gui: false, load_error: null, missing: false, loaded: true, ...over };
}

beforeEach(() => {
  vi.spyOn(capabilitiesAdminClient, "list").mockResolvedValue([
    cap({}),
    cap({ name: "fresh", label: "Fresh", enabled: false, loaded: false, tools: [] }),
    cap({ name: "broken", label: "Broken", enabled: false, load_error: "RuntimeError: boom" }),
    cap({ name: "gone", label: "Gone", enabled: false, missing: true }),
  ]);
});
afterEach(() => vi.restoreAllMocks());

async function mounted() {
  const wrapper = mount(CapabilitiesAdminView);
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
