import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "./http";
import { usageClient } from "./UsageClient";

vi.mock("./http", () => ({ apiRequest: vi.fn() }));

const request = vi.mocked(apiRequest);

beforeEach(() => {
  vi.clearAllMocks();
  request.mockResolvedValue({} as never);
});

describe("usageClient", () => {
  it("asks for the last n days", async () => {
    await usageClient.mine(30);

    expect(request).toHaveBeenCalledExactlyOnceWith("GET", "/api/usage?days=30");
  });

  it("asks from a day when one is given", async () => {
    await usageClient.mine(30, "2026-10-01");

    expect(request).toHaveBeenCalledExactlyOnceWith("GET", "/api/usage?days=30&since=2026-10-01");
  });

  it("does the same for every account's totals", async () => {
    await usageClient.allAccounts(7);
    await usageClient.allAccounts(30, "2026-10-01");

    expect(request.mock.calls).toEqual([
      ["GET", "/api/admin/usage?days=7"],
      ["GET", "/api/admin/usage?days=30&since=2026-10-01"],
    ]);
  });

  it("leaves out an empty since", async () => {
    await usageClient.mine(7, "");

    expect(request).toHaveBeenCalledExactlyOnceWith("GET", "/api/usage?days=7");
  });

  it("escapes what it puts in the address", async () => {
    await usageClient.mine(7, "2026-10-01&days=1");

    expect(request.mock.calls[0]![1]).toBe("/api/usage?days=7&since=2026-10-01%26days%3D1");
  });
});
