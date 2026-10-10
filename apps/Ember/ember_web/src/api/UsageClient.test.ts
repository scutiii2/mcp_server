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

  it("leaves out an empty since", async () => {
    await usageClient.mine(7, "");

    expect(request).toHaveBeenCalledExactlyOnceWith("GET", "/api/usage?days=7");
  });

  it("adds the grouping and filters", async () => {
    await usageClient.mine(30, undefined, { groupBy: "provider", agent: "calc", provider: "open ai" });

    expect(request).toHaveBeenCalledExactlyOnceWith("GET", "/api/usage?days=30&group_by=provider&agent=calc&provider=open%20ai");
  });

  it("asks for the rows, newest first, with a limit", async () => {
    await usageClient.records(7, "2026-10-01", { agent: "calc", limit: 100 });

    expect(request).toHaveBeenCalledExactlyOnceWith("GET", "/api/usage/records?days=7&since=2026-10-01&agent=calc&limit=100");
  });

  it("escapes what it puts in the address", async () => {
    await usageClient.mine(7, "2026-10-01&days=1");

    expect(request.mock.calls[0]![1]).toBe("/api/usage?days=7&since=2026-10-01%26days%3D1");
  });
});
