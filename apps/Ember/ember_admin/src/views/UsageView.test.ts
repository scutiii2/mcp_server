import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { usageClient, type MyUsage, type UsageRecordRow } from "../api/UsageClient";
import { ApiError } from "../api/http";
import { useAuthStore } from "../stores/auth";
import { downloadText } from "../utils/downloadText";
import UsageView from "./UsageView.vue";

vi.mock("../api/UsageClient", () => ({ usageClient: { allAccounts: vi.fn(), account: vi.fn(), records: vi.fn() } }));
vi.mock("../utils/downloadText", () => ({ downloadText: vi.fn(), exportFileName: (s: string) => s + ".md" }));
const api = vi.mocked(usageClient);
const users = [
  { account_id: 2, username: "alice", tokens: 123, turns: 1, last_used_at: null },
  { account_id: 3, username: "bob", tokens: 456, turns: 2, last_used_at: null },
  { account_id: 4, username: "empty", tokens: 0, turns: 0, last_used_at: null },
];
const report = (tokens = 123): MyUsage => ({
  six_hour: { used: tokens, limit: 1000, reset_at: null }, weekly: { used: tokens, limit: 0, reset_at: null },
  report: { days: 30, since: "2026-10-01T00:00:00", total_tokens: tokens, input_tokens: tokens, output_tokens: 0,
    summary_tokens: 0, turns: tokens ? 1 : 0, chats: 0, by_agent: [], daily: [], hourly: Array(24).fill(0), group_by: "agent", groups: [] },
});
const row = (agent: string): UsageRecordRow => ({
  id: 1, turn_id: "t", kind: "chat", chat_id: null, agent, agent_id: agent,
  provider_id: null, gateway: null, model: null, input_tokens: null, output_tokens: null,
  total_tokens: 999, started_at: null, finished_at: null, delegated_by: null, created_at: "2026-10-10T12:00:00",
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
let wrapper: ReturnType<typeof mount>;
beforeEach(() => {
  vi.resetAllMocks();
  setActivePinia(createPinia());
  useAuthStore().account = { id: 1, username: "observer", email: "o@example.com", email_verified: true, roles: [], permissions: ["usage.all.view"] };
  api.allAccounts.mockResolvedValue(users);
  api.account.mockImplementation(async id => report(id === 2 ? 123 : id === 3 ? 456 : 0));
  api.records.mockResolvedValue([]);
});
afterEach(() => wrapper?.unmount());
async function show() { wrapper = mount(UsageView); await flushPromises(); return wrapper; }
async function select(name: string) { await wrapper.get(`[aria-label="View usage for ${name}"]`).trigger("click"); await flushPromises(); }
async function period(label: string) { await wrapper.findAll(".ranges button").find(b => b.text() === label)!.trigger("click"); await flushPromises(); }

it("loads all accounts for a usage-only observer and waits for selection", async () => {
  await show();
  expect(api.allAccounts).toHaveBeenCalledWith(30, undefined);
  expect(wrapper.text()).toContain("empty");
  expect(wrapper.text()).toContain("Select a user");
  expect(api.account).not.toHaveBeenCalled();
});
it("requests selected user detail and annual heatmap, then exports that user's identity", async () => {
  await show(); await select("alice");
  expect(api.account).toHaveBeenCalledWith(2, 30, undefined, { groupBy: "agent" });
  expect(api.account).toHaveBeenCalledWith(2, 366);
  expect(api.records).toHaveBeenCalledWith(2, 30, undefined, { limit: 100 });
  expect(wrapper.get(".usage-details").text()).toContain("alice");
  await wrapper.get("button.export").trigger("click");
  expect(vi.mocked(downloadText).mock.calls[0]![1]).toContain("# Token usage - alice");
});
it("refreshes period and grouping without refetching the annual heatmap", async () => {
  await show(); await select("bob"); await period("7 days");
  expect(api.allAccounts).toHaveBeenLastCalledWith(7, undefined);
  expect(api.account).toHaveBeenLastCalledWith(3, 7, undefined, { groupBy: "agent" });
  await wrapper.findAll("button").find(b => b.text() === "Model")!.trigger("click"); await flushPromises();
  expect(api.account).toHaveBeenLastCalledWith(3, 7, undefined, { groupBy: "model" });
  expect(api.account.mock.calls.filter(c => c[1] === 366)).toHaveLength(1);
});
it("discards late user reports, rows and annual replies and disables export immediately", async () => {
  const old = deferred<MyUsage>();
  const oldRows = deferred<UsageRecordRow[]>();
  api.account.mockImplementation(id => id === 2 ? old.promise : Promise.resolve(report(456)));
  api.records.mockImplementation(id => id === 2 ? oldRows.promise : Promise.resolve([]));
  await show(); await select("alice"); await select("bob");
  old.resolve(report(999)); oldRows.resolve([row("old-alice-agent")]); await flushPromises();
  expect(wrapper.get(".usage-details").text()).toContain("bob");
  expect(wrapper.get(".usage-details").text()).not.toContain("999");
  expect(wrapper.get(".usage-details").text()).not.toContain("old-alice-agent");
  const next = deferred<MyUsage>(); api.account.mockReturnValue(next.promise);
  await select("alice");
  expect(wrapper.find(".usage-details").exists()).toBe(false);
  expect(wrapper.get("button.export").attributes("disabled")).toBeDefined();
});
it("discards out-of-order period replies", async () => {
  await show(); await select("alice");
  const old = deferred<MyUsage>();
  api.account.mockImplementation((_id, days) => days === 7 ? old.promise : Promise.resolve(report(90)));
  await period("7 days"); await period("90 days");
  old.resolve(report(999)); await flushPromises();
  expect(wrapper.get(".usage-details").text()).not.toContain("999");
  await wrapper.get("button.export").trigger("click");
  expect(vi.mocked(downloadText).mock.calls[0]![1]).toContain("Range: 90 days");
});
it("clears all private state when the logged-in account changes", async () => {
  await show(); await select("alice");
  useAuthStore().account = null; await flushPromises();
  expect(wrapper.find(".usage-details").exists()).toBe(false);
  expect(wrapper.text()).not.toContain("alice");
});
it("ignores pending summary, reports, annual data and records after an account switch", async () => {
  await show();
  const oldSummary = deferred<typeof users>();
  const oldReport = deferred<MyUsage>();
  const oldRows = deferred<UsageRecordRow[]>();
  api.allAccounts.mockReturnValueOnce(oldSummary.promise);
  api.account.mockReturnValue(oldReport.promise);
  api.records.mockReturnValue(oldRows.promise);
  await select("alice"); await period("7 days");
  useAuthStore().account = { id: 9, username: "other", email: "other@example.com", email_verified: true, roles: [], permissions: ["usage.all.view"] };
  api.allAccounts.mockResolvedValue([]);
  oldSummary.resolve([{ ...users[0]!, username: "old-account-only" }]);
  oldReport.resolve(report(999)); oldRows.resolve([row("old-private-agent")]);
  await flushPromises();
  expect(wrapper.find(".usage-details").exists()).toBe(false);
  expect(wrapper.text()).not.toContain("old-account-only");
  expect(wrapper.text()).not.toContain("old-private-agent");
  expect(wrapper.get("button.export").attributes("disabled")).toBeDefined();
});
it("keeps the report when optional requests fail", async () => {
  api.records.mockRejectedValue(new Error("Rows unavailable"));
  api.account.mockImplementation(async (_id, days) => { if (days === 366) throw new Error("Annual unavailable"); return report(); });
  await show(); await select("alice");
  expect(wrapper.get(".usage-details").text()).toContain("123");
  expect(wrapper.text()).toContain("Could not load recent calls");
  expect(wrapper.text()).toContain("Could not load annual activity");
});
it("shows main errors separately and retries without stale exports", async () => {
  await show(); await select("alice");
  api.account.mockRejectedValueOnce(new Error("Report unavailable"));
  await period("7 days");
  expect(wrapper.text()).toContain("Report unavailable");
  expect(wrapper.find(".usage-details").exists()).toBe(false);
  expect(wrapper.get("button.export").attributes("disabled")).toBeDefined();
  await wrapper.get("button.detail-retry").trigger("click"); await flushPromises();
  expect(wrapper.find(".usage-details").exists()).toBe(true);
});
it("returns to the summary when the target has been deleted", async () => {
  await show();
  api.account.mockRejectedValue(new ApiError(404, "Account not found"));
  api.allAccounts.mockResolvedValue(users.slice(1));
  await select("alice");
  expect(wrapper.find(".usage-details").exists()).toBe(false);
  expect(wrapper.text()).toContain("Select a user");
  expect(wrapper.text()).not.toContain("alice");
});
it("distinguishes summary errors from zero usage and supports retry", async () => {
  api.allAccounts.mockRejectedValueOnce(new Error("Summary unavailable"));
  await show(); expect(wrapper.text()).toContain("Summary unavailable");
  expect(wrapper.text()).not.toContain("No accounts");
  await wrapper.get("button.summary-retry").trigger("click"); await flushPromises();
  await select("empty");
  expect(wrapper.get(".usage-details").text()).toContain("No usage in this period");
});
