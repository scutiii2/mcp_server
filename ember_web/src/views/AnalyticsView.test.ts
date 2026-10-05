import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { logsClient, type AnalyticsReport, type LogKind } from "../api/LogsClient";
import { useAuthStore } from "../stores/auth";
import AnalyticsView from "./AnalyticsView.vue";

vi.mock("../api/LogsClient", () => ({ logsClient: { index: vi.fn(), list: vi.fn(), analytics: vi.fn() } }));

const index = vi.mocked(logsClient.index);
const list = vi.mocked(logsClient.list);
const analytics = vi.mocked(logsClient.analytics);

const ALL: LogKind[] = ["action", "error", "chat_trace"];

function report(kinds: LogKind[] = ALL, period: AnalyticsReport["period"] = "7d"): AnalyticsReport {
  const zero = (n: number) => Object.fromEntries(kinds.map((k) => [k, n]));
  return {
    period,
    bucket: "day",
    kinds,
    totals: Object.fromEntries(kinds.map((k) => [k, { current: 12, previous: 6 }])),
    series: ["2026-10-04T00:00:00", "2026-10-05T00:00:00"].map((bucket) => ({ bucket, counts: zero(6) })),
    top_sources: Object.fromEntries(kinds.map((k) => [k, [{ source: `${k}.src`, count: 9 }]])),
    accounts: Object.fromEntries(
      kinds.map((k) => [
        k,
        [
          { account_id: 5, username: "alice", count: 7 },
          { account_id: null, username: null, count: 2 },
        ],
      ]),
    ),
    heatmap: [{ weekday: 1, hour: 13, count: 4 }],
  };
}

async function mountView() {
  setActivePinia(createPinia());
  useAuthStore().account = { id: 1, username: "root", email: "r@example.com", email_verified: true, roles: [], permissions: [] };
  const wrapper = mount(AnalyticsView);
  await flushPromises();
  return wrapper;
}

const button = (wrapper: Awaited<ReturnType<typeof mountView>>, label: string) =>
  wrapper.findAll("button").find((b) => b.text() === label)!;

beforeEach(() => {
  vi.clearAllMocks();
  analytics.mockResolvedValue(report());
  index.mockResolvedValue({ kinds: ALL, accounts: [{ id: 5, username: "alice" }] });
  list.mockResolvedValue([]);
});

describe("AnalyticsView overview", () => {
  it("loads the last 7 days and draws every chart", async () => {
    const wrapper = await mountView();

    expect(analytics).toHaveBeenCalledExactlyOnceWith("7d");
    expect(wrapper.findAll(".tile .label").map((l) => l.text())).toEqual(["Activity", "Errors", "Chat turns"]);
    expect(wrapper.find(".plot").exists()).toBe(true);
    expect(wrapper.findAll(".heat .grid .cell")).toHaveLength(7 * 24);
    expect(wrapper.text()).toContain("Top sources");
    expect(wrapper.text()).toContain("error.src");
    expect(wrapper.text()).toContain("Busiest accounts");
    expect(wrapper.text()).toContain("alice");
    expect(wrapper.text()).toContain("Server");
  });

  it("asks again for another range", async () => {
    analytics.mockResolvedValueOnce(report()).mockResolvedValueOnce(report(ALL, "30d"));
    const wrapper = await mountView();

    await button(wrapper, "30d").trigger("click");
    await flushPromises();

    expect(analytics).toHaveBeenLastCalledWith("30d");
    expect(wrapper.find(".tile .delta").text()).toContain("vs previous 30 days");
  });

  it("refreshes on demand", async () => {
    const wrapper = await mountView();

    await button(wrapper, "Refresh").trigger("click");
    await flushPromises();

    expect(analytics).toHaveBeenCalledTimes(2);
  });

  it("draws only the kinds ember_api sent", async () => {
    analytics.mockResolvedValue(report(["action"]));
    const wrapper = await mountView();

    expect(wrapper.findAll(".tile")).toHaveLength(1);
    expect(wrapper.findAll(".legend li").map((l) => l.text())).toEqual(["Activity"]);
    expect(wrapper.findAll(".group")).toHaveLength(2); // one per card
    expect(wrapper.text()).not.toContain("Errors");
  });

  it("shows only the busiest five rows of a kind", async () => {
    const many = report(["action"]);
    many.top_sources.action = Array.from({ length: 10 }, (_, i) => ({ source: `src.${i}`, count: 10 - i }));
    analytics.mockResolvedValue(many);
    const wrapper = await mountView();

    expect(wrapper.text()).toContain("src.4");
    expect(wrapper.text()).not.toContain("src.5");
  });

  it("shows the error when the report cannot be loaded", async () => {
    analytics.mockRejectedValue(new Error("boom"));
    const wrapper = await mountView();

    expect(wrapper.find(".error").text()).toContain("boom");
    expect(wrapper.find(".tiles").exists()).toBe(false);
  });
});

describe("AnalyticsView entries", () => {
  it("opens the entries list on its first kind from the Entries tab", async () => {
    const wrapper = await mountView();

    await button(wrapper, "Entries").trigger("click");
    await flushPromises();

    expect(wrapper.find(".plot").exists()).toBe(false);
    expect(list).toHaveBeenCalledWith("action", "server");
  });

  it("opens an account's entries of that kind when its row is clicked", async () => {
    const wrapper = await mountView();
    const errorCard = wrapper.findAll(".pair .card")[1]!.findAll(".group")[1]!;

    await errorCard.findAll("button")[0]!.trigger("click"); // alice's errors
    await flushPromises();

    expect(list).toHaveBeenCalledWith("error", 5);
    expect(wrapper.find("select").element.value).toBe("5");
  });

  it("opens the server's entries when the server's row is clicked", async () => {
    const wrapper = await mountView();
    const actionCard = wrapper.findAll(".pair .card")[1]!.findAll(".group")[0]!;

    await actionCard.findAll("button")[1]!.trigger("click");
    await flushPromises();

    expect(list).toHaveBeenCalledWith("action", "server");
  });

  it("goes back to the plain list, not the clicked account, when the tab is picked again", async () => {
    const wrapper = await mountView();
    await wrapper.findAll(".pair .card")[1]!.findAll(".group")[1]!.findAll("button")[0]!.trigger("click");
    await flushPromises();
    list.mockClear();

    await button(wrapper, "Overview").trigger("click");
    await button(wrapper, "Entries").trigger("click");
    await flushPromises();

    expect(list).toHaveBeenCalledWith("action", "server");
    expect(list).not.toHaveBeenCalledWith("error", 5);
  });
});
