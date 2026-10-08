import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { trafficClient, type TrafficReport } from "../../api/TrafficClient";
import TrafficPanel from "./TrafficPanel.vue";

vi.mock("../../api/TrafficClient", () => ({ trafficClient: { analytics: vi.fn() } }));

const analytics = vi.mocked(trafficClient.analytics);

function report(overrides: Partial<TrafficReport> = {}): TrafficReport {
  return {
    period: "7d",
    bucket: "day",
    latency_cap_ms: 5000,
    totals: {
      requests: { current: 120, previous: 100 },
      error_rate: { current: 0.025, previous: 0.01 },
      p95_ms: { current: 250, previous: 100 },
      upstream_failures: { current: 3, previous: 0 },
    },
    series: [
      { bucket: "2026-10-04T00:00:00", requests: { "2xx": 90, "3xx": 0, "4xx": 7, "5xx": 3 }, p50_ms: 50, p95_ms: 250 },
      { bucket: "2026-10-05T00:00:00", requests: { "2xx": 20, "3xx": 0, "4xx": 0, "5xx": 0 }, p50_ms: null, p95_ms: null },
    ],
    routes: {
      busiest: [
        { name: "GET /api/chats", count: 100, error_rate: 0.01, p95_ms: 250 },
        { name: "POST /api/chats/{chat_id}/turns", count: 6, error_rate: 0, p95_ms: 5000 },
      ],
      slowest: [{ name: "POST /api/chats/{chat_id}/turns", count: 6, error_rate: 0, p95_ms: 5000 }],
    },
    upstream: [
      {
        target: "ai_agent",
        calls: 30,
        failures: 2,
        failure_rate: 2 / 30,
        p95_ms: 5000,
        tools: [
          { name: "ask", calls: 10, failures: 2, p95_ms: 5000 },
          { name: "status", calls: 20, failures: 0, p95_ms: 50 },
        ],
      },
    ],
    ...overrides,
  };
}

async function mountPanel(props: { range?: "24h" | "7d" | "30d" | "90d"; refresh?: number } = {}) {
  const wrapper = mount(TrafficPanel, { props: { range: "7d", refresh: 0, ...props } });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  vi.clearAllMocks();
  analytics.mockResolvedValue(report());
});

describe("TrafficPanel", () => {
  it("loads the range and writes the four headline numbers with their change", async () => {
    const wrapper = await mountPanel();

    expect(analytics).toHaveBeenCalledExactlyOnceWith("7d");
    const tiles = wrapper.findAll(".tile");
    expect(tiles.map((t) => t.find(".label").text())).toEqual(["Requests", "Error rate", "Slowest 5%", "Upstream failures"]);
    expect(tiles.map((t) => t.find(".value").text())).toEqual(["120", "2.5%", "250 ms", "3"]);
    expect(tiles.map((t) => t.find(".delta").text())).toEqual([
      "▲ +20% vs previous 7 days",
      "▲ +1.5 pts vs previous 7 days",
      "▲ +150% vs previous 7 days",
      "new vs previous 7 days",
    ]);
  });

  it("marks only the changes that are bad news", async () => {
    const wrapper = await mountPanel();

    expect(wrapper.findAll(".tile .delta").map((d) => d.classes("bad"))).toEqual([false, true, true, true]);
  });

  it("does not call fewer errors or faster answers bad", async () => {
    const better = report();
    better.totals.error_rate = { current: 0.005, previous: 0.02 };
    better.totals.p95_ms = { current: 50, previous: 250 };
    better.totals.upstream_failures = { current: 0, previous: 4 };
    analytics.mockResolvedValue(better);

    const wrapper = await mountPanel();

    expect(wrapper.findAll(".tile .delta").map((d) => d.classes("bad"))).toEqual([false, false, false, false]);
  });

  it("draws requests by status class and the two latency lines", async () => {
    const wrapper = await mountPanel();

    const [requests, latency] = wrapper.findAll(".chart");
    expect(requests!.findAll(".legend li").map((l) => l.text())).toEqual(["2xx success", "3xx redirect", "4xx client error", "5xx server error"]);
    expect(requests!.findAll(".col")).toHaveLength(2);
    expect(latency!.findAll(".legend li").map((l) => l.text())).toEqual(["Median (p50)", "Slowest 5% (p95)"]);
    // the empty day is a gap, not a zero: one bucket with a value is a lone dot per line
    expect(latency!.findAll(".dot:not(.ringed)")).toHaveLength(2);
  });

  it("writes a time at the cap as 'at least', in the slowest list and the chart note", async () => {
    const wrapper = await mountPanel();

    const slowest = wrapper.findAll(".pair .card")[1]!;
    expect(slowest.find("h3").text()).toBe("Slowest routes");
    expect(slowest.find(".value").text()).toBe("5 s+");
    expect(wrapper.text()).toContain("5 s+ means at least that");
  });

  it("lists the busiest routes by their template", async () => {
    const wrapper = await mountPanel();

    const busiest = wrapper.findAll(".pair .card")[0]!;
    expect(busiest.findAll(".label").map((l) => l.text())).toEqual(["GET /api/chats", "POST /api/chats/{chat_id}/turns"]);
    expect(busiest.findAll(".value").map((v) => v.text())).toEqual(["100", "6"]);
  });

  it("summarises each upstream target and names the tools that failed", async () => {
    const wrapper = await mountPanel();

    const block = wrapper.find(".group");
    expect(block.find("h4").text()).toBe("ai_agent");
    expect(block.find(".summary").text()).toBe("30 calls · 2 failed (6.7%) · slowest 5% 5 s+");
    expect(block.findAll(".label").map((l) => l.text())).toEqual(["ask · 2 failed", "status"]);
  });

  it("says nothing was recorded yet, and still shows the empty charts", async () => {
    const empty = report({ upstream: [], routes: { busiest: [], slowest: [] } });
    empty.totals = {
      requests: { current: 0, previous: 0 },
      error_rate: { current: null, previous: null },
      p95_ms: { current: null, previous: null },
      upstream_failures: { current: 0, previous: 0 },
    };
    empty.series = empty.series.map((p) => ({ ...p, requests: { "2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0 }, p50_ms: null, p95_ms: null }));
    analytics.mockResolvedValue(empty);

    const wrapper = await mountPanel();

    expect(wrapper.find(".idle").text()).toContain("No traffic recorded in the last 7 days yet");
    expect(wrapper.findAll(".tile .value").map((v) => v.text())).toEqual(["0", "–", "–", "0"]);
    expect(wrapper.findAll(".none").map((n) => n.text())).toEqual(["No requests in this range.", "No requests in this range."]);
    expect(wrapper.text()).toContain("No calls to ai_agent or mcp_server in this range.");
    expect(wrapper.find(".idle").exists()).toBe(true);
  });

  it("does not say it is idle when there is traffic", async () => {
    expect((await mountPanel()).find(".idle").exists()).toBe(false);
  });

  it("asks again for another range and when told to refresh", async () => {
    const wrapper = await mountPanel();

    await wrapper.setProps({ range: "30d" });
    await flushPromises();
    await wrapper.setProps({ refresh: 1 });
    await flushPromises();

    expect(analytics.mock.calls.map(([range]) => range)).toEqual(["7d", "30d", "30d"]);
  });

  it("reports loading while it fetches", async () => {
    const wrapper = mount(TrafficPanel, { props: { range: "7d", refresh: 0 } });
    await flushPromises();

    expect(wrapper.emitted("update:loading")).toEqual([[true], [false]]);
  });

  it("shows the error when the report cannot be loaded", async () => {
    analytics.mockRejectedValue(new Error("boom"));

    const wrapper = await mountPanel();

    expect(wrapper.find(".error").text()).toContain("boom");
    expect(wrapper.find(".tiles").exists()).toBe(false);
  });
});
