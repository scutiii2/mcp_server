import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { useAuthStore } from "./auth";
import { useEntryAgentStore } from "./entryAgent";

const request = vi.hoisted(() => vi.fn());
const status = vi.hoisted(() => vi.fn());
vi.mock("../api/http", async (original) => ({ ...(await original<typeof import("../api/http")>()), apiRequest: request }));
vi.mock("../api/AiAgentClient", () => ({ AiAgentClient: vi.fn(function () { return { status }; }) }));

beforeEach(() => {
  setActivePinia(createPinia());
  useAuthStore().account = {
    id: 1, username: "root", email: "r@example.com", email_verified: true, roles: [], permissions: ["chat.use", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"],
  };
  request.mockReset();
  status.mockReset();
});

describe("entry agent store", () => {
  it("loads the entry agent and checks that it is available", async () => {
    request.mockResolvedValue({ id: "main", label: "Ember" });
    status.mockResolvedValue({ available: true });
    const store = useEntryAgentStore();

    await store.refresh();

    expect(request).toHaveBeenCalledWith("GET", "/api/agent");
    expect(store.entry).toEqual({ id: "main", label: "Ember" });
    expect(store.labels).toEqual({ main: "Ember" });
    expect(store.available).toBe(true);
  });

  it("marks an agent whose status says unavailable (or that cannot be reached)", async () => {
    request.mockResolvedValue({ id: "main", label: "Ember" });
    status.mockResolvedValue({ available: false });
    const store = useEntryAgentStore();
    await store.refresh();
    expect(store.available).toBe(false);

    status.mockRejectedValue(new Error("down"));
    await store.refresh();
    expect(store.available).toBe(false);
  });

  it("keeps the server's message when no agent is running", async () => {
    request.mockRejectedValue(new ApiError(503, "No agent is running"));
    const store = useEntryAgentStore();

    await store.refresh();

    expect(store.entry).toBeNull();
    expect(store.labels).toEqual({});
    expect(store.loadError).toBe("No agent is running");
  });

  it("forgets the agent when another user logs in", async () => {
    request.mockResolvedValue({ id: "main", label: "Ember" });
    status.mockResolvedValue({ available: true });
    const store = useEntryAgentStore();
    await store.refresh();

    useAuthStore().account = { ...useAuthStore().account!, id: 2 };
    await flushPromises();

    expect(request).toHaveBeenCalledTimes(2); // reloaded for the new user
  });
});
