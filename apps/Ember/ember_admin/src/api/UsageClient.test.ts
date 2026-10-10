import { beforeEach, expect, it, vi } from "vitest";
import { apiRequest } from "./http";
import { usageClient } from "./UsageClient";

vi.mock("./http", () => ({ apiRequest: vi.fn() }));
beforeEach(() => vi.clearAllMocks());

it("uses only admin usage routes with the target and encoded query", async () => {
  await usageClient.allAccounts(30, "2026-10-01");
  await usageClient.account(2, 7, undefined, { groupBy: "provider", agent: "a b", provider: "x&y" });
  await usageClient.records(3, 90, undefined, { limit: 100 });
  expect(vi.mocked(apiRequest).mock.calls).toEqual([
    ["GET", "/api/admin/usage?days=30&since=2026-10-01"],
    ["GET", "/api/admin/usage/2?days=7&group_by=provider&agent=a%20b&provider=x%26y"],
    ["GET", "/api/admin/usage/3/records?days=90&limit=100"],
  ]);
});

it("propagates errors", async () => {
  vi.mocked(apiRequest).mockRejectedValueOnce(new Error("Denied"));
  await expect(usageClient.account(2, 30)).rejects.toThrow("Denied");
});
