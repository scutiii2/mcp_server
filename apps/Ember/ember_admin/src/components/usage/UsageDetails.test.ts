import { mount } from "@vue/test-utils";
import { expect, it } from "vitest";
import type { MyUsage } from "../../api/UsageClient";
import UsageDetails from "./UsageDetails.vue";

it("labels the target and emits grouping changes without fetching personal data", async () => {
  const usage: MyUsage = {
    six_hour: { used: 0, limit: 0, reset_at: null }, weekly: { used: 0, limit: 0, reset_at: null },
    report: { days: 30, since: "2026-10-01", total_tokens: 0, input_tokens: 0, output_tokens: 0,
      summary_tokens: 0, turns: 0, chats: 0, by_agent: [], daily: [], hourly: Array(24).fill(0), group_by: "agent", groups: [] },
  };
  const w = mount(UsageDetails, { props: { username: "alice", usage, year: null, records: [], recordsFailed: false, yearFailed: false, loading: false, groupBy: "agent" } });
  expect(w.attributes("aria-label")).toBe("Usage for alice");
  expect(w.text()).toContain("No limit");
  expect(w.text()).toContain("No usage in this period");
  await w.findAll("button").find(b => b.text() === "Provider")!.trigger("click");
  expect(w.emitted("group")).toEqual([["provider"]]);
  w.unmount();
});
