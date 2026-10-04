import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EntryAgentTag from "./EntryAgentTag.vue";
import { useEntryAgentStore } from "../stores/entryAgent";

vi.mock("../api/http", async (original) => ({ ...(await original<typeof import("../api/http")>()), apiRequest: vi.fn() }));

beforeEach(() => setActivePinia(createPinia()));

function tag() {
  return mount(EntryAgentTag, { global: { plugins: [] } });
}

describe("EntryAgentTag", () => {
  it("names the agent the user is talking to", () => {
    const store = useEntryAgentStore();
    store.entry = { id: "main", label: "Ember" };
    store.available = true;
    store.refresh = vi.fn();

    expect(tag().text()).toContain("Talking to Ember");
  });

  it("says when it is unavailable, and when none is running", () => {
    const store = useEntryAgentStore();
    store.refresh = vi.fn();
    store.entry = { id: "main", label: "Ember" };
    store.available = false;
    expect(tag().text()).toContain("unavailable");

    store.entry = null;
    store.loadError = "No agent is running";
    expect(tag().text()).toContain("No agent is running");
  });
});
