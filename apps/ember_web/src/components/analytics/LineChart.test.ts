import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { formatDuration } from "../../utils/trafficAnalytics";
import LineChart from "./LineChart.vue";

const lines = [
  { id: "p50", label: "Median", color: "blue" },
  { id: "p95", label: "Slowest 5%", color: "purple" },
];
const series = [
  { bucket: "2026-10-03T00:00:00", values: { p50: 50, p95: 100 } },
  { bucket: "2026-10-04T00:00:00", values: { p50: null, p95: null } }, // no requests: a gap, not a zero
  { bucket: "2026-10-05T00:00:00", values: { p50: 100, p95: 250 } },
];

function chart(props: Partial<InstanceType<typeof LineChart>["$props"]> = {}) {
  return mount(LineChart, { props: { series, lines, bucket: "day", label: "Response time", format: formatDuration, ...props } });
}

const points = (wrapper: ReturnType<typeof chart>) => wrapper.findAll("polyline").map((p) => p.attributes("points"));

describe("LineChart", () => {
  it("scales to a clean axis top and writes the ticks with its formatter", () => {
    // the slowest value is 250 ms: a clean top whose half is whole too
    expect(chart().findAll(".ytick").map((t) => t.text())).toEqual(["400 ms", "200 ms", "0 ms"]);
    expect(chart({ series: [{ bucket: series[0]!.bucket, values: { p50: 1500 } }] }).findAll(".ytick")[0]!.text()).toBe("2 s");
  });

  it("leaves a gap at a bucket without a value instead of drawing a zero", () => {
    const wrapper = chart();

    // two buckets with a value, split by one without: no line, a dot at each end instead
    expect(points(wrapper)).toEqual([]);
    expect(wrapper.findAll(".dot:not(.ringed)")).toHaveLength(4);
  });

  it("joins consecutive buckets into one line per part, newest on the right", () => {
    const wrapper = chart({
      series: [
        { bucket: "2026-10-03T00:00:00", values: { p50: 100, p95: 200 } },
        { bucket: "2026-10-04T00:00:00", values: { p50: 200, p95: 400 } },
      ],
    });

    // x is the middle of each of the two buckets; y runs from the top of the 0-100 box (400 ms)
    expect(points(wrapper)).toEqual(["25.00,75.00 75.00,50.00", "25.00,50.00 75.00,0.00"]);
    expect(wrapper.findAll("polyline").map((p) => p.attributes("stroke"))).toEqual(["blue", "purple"]);
  });

  it("reads a bucket with the arrow keys: every line, '–' where there is no value, a ring on each point", async () => {
    const wrapper = chart();
    const plot = wrapper.find(".plot");

    await plot.trigger("keydown", { key: "Home" });
    expect(wrapper.find(".tooltip .when").text()).toBe("Sat, Oct 3");
    expect(wrapper.findAll(".tooltip .line").map((l) => l.text())).toEqual(["50 ms Median", "100 ms Slowest 5%"]);
    expect(wrapper.findAll(".dot.ringed")).toHaveLength(2);

    await plot.trigger("keydown", { key: "ArrowRight" });
    expect(wrapper.findAll(".tooltip .line").map((l) => l.text())).toEqual(["– Median", "– Slowest 5%"]);
    expect(wrapper.findAll(".dot.ringed")).toHaveLength(0);

    await plot.trigger("keydown", { key: "Escape" });
    expect(wrapper.find(".tooltip").exists()).toBe(false);
  });

  it("has a table twin with the same numbers", async () => {
    const wrapper = chart();

    await wrapper.find(".head .chip").trigger("click");

    expect(wrapper.find(".plot").exists()).toBe(false);
    expect(wrapper.findAll("tbody tr").map((r) => r.findAll("th, td").map((c) => c.text()))).toEqual([
      ["Sat, Oct 3", "50 ms", "100 ms"],
      ["Sun, Oct 4", "–", "–"],
      ["Mon, Oct 5", "100 ms", "250 ms"],
    ]);
    expect(wrapper.find("caption").text()).toBe("Response time per day, UTC");
  });

  it("says so when no bucket has a value, and dims while refetching", () => {
    const wrapper = chart({ series: [series[1]!], emptyText: "No requests in this range.", loading: true });

    expect(wrapper.find(".none").text()).toBe("No requests in this range.");
    expect(wrapper.find(".chart").classes()).toContain("dim");
  });

  it("names itself for screen readers", () => {
    expect(chart().find(".plot").attributes("aria-label")).toMatch(/^Response time over time/);
  });
});
