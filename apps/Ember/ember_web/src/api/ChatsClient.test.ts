import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatsClient } from "./ChatsClient";
import { apiRequest } from "./http";

vi.mock("./http", () => ({ apiRequest: vi.fn() }));

const request = vi.mocked(apiRequest);

beforeEach(() => {
  vi.clearAllMocks();
  request.mockResolvedValue({} as never);
});

describe("chatsClient.update", () => {
  it("sends only the fields that change", async () => {
    await chatsClient.update("c-1", { pinned: true });

    expect(request).toHaveBeenCalledExactlyOnceWith("PATCH", "/api/chats/c-1", { pinned: true });
  });

  it("sends folder_id null to take a chat out of its folder", async () => {
    await chatsClient.update("c-1", { folder_id: null });

    expect(request).toHaveBeenCalledExactlyOnceWith("PATCH", "/api/chats/c-1", { folder_id: null });
  });

  it("rename keeps sending only the title", async () => {
    await chatsClient.rename("c-1", "New");

    expect(request).toHaveBeenCalledExactlyOnceWith("PATCH", "/api/chats/c-1", { title: "New" });
  });
});
