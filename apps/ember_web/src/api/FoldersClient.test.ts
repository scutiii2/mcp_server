import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "./http";
import { foldersClient } from "./FoldersClient";

vi.mock("./http", () => ({ apiRequest: vi.fn() }));

const request = vi.mocked(apiRequest);

beforeEach(() => {
  vi.clearAllMocks();
  request.mockResolvedValue({} as never);
});

describe("foldersClient", () => {
  it("lists folders", async () => {
    await foldersClient.list();

    expect(request).toHaveBeenCalledExactlyOnceWith("GET", "/api/chat-folders");
  });

  it("creates a folder from a name", async () => {
    await foldersClient.create("Work");

    expect(request).toHaveBeenCalledExactlyOnceWith("POST", "/api/chat-folders", { name: "Work" });
  });

  it("renames and reorders with separate PATCH bodies", async () => {
    await foldersClient.rename(3, "Home");
    await foldersClient.reorder(3, 7);

    expect(request.mock.calls).toEqual([
      ["PATCH", "/api/chat-folders/3", { name: "Home" }],
      ["PATCH", "/api/chat-folders/3", { position: 7 }],
    ]);
  });

  it("deletes a folder", async () => {
    await foldersClient.remove(3);

    expect(request).toHaveBeenCalledExactlyOnceWith("DELETE", "/api/chat-folders/3");
  });
});
