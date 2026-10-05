import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { AnalyticsReport } from "../../api/LogsClient";
import ActivityChart from "./ActivityChart.vue";
import BarList from "./BarList.vue";
import HourHeatmap from "./HourHeatmap.vue";
import KindStatTile from "./KindStatTile.vue";

const series: AnalyticsReport["series"] = [
  { bucket: "2026-10-03T00:00:00", counts: { action: 4, error: 0, chat_trace: 0 } },
  { bucket: "2026-10-04T00:00:00", counts: { action: 2, error: 1, chat_trace: 3 } },
  { bucket: "2026-10-05T00:00:00", counts: { action: 0, error: 0, chat_trace: 0 } },
];
const KINDS = ["action", "error", "chat_trace"] as const;

function chart(props: Partial<InstanceType<typeof ActivityChart>["$props"]> = {}) {
  return mount(ActivityChart, { props: { series, kinds: [...KINDS], bucket: "day", ...props } });
}

describe("ActivityChart", () => {
  it("draws a column per bucket with a segment per kind that has entries", () => {
    const wrapper = chart();

    expect(wrapper.findAll(".col")).toHaveLength(3);
    expect(wrapper.findAll(".col").map((c) => c.findAll(".seg").length)).toEqual([1, 3, 0]);
  });

  it("scales the columns to a clean axis top and rounds only the top segment", () => {
    const wrapper = chart();

    // the busiest bucket holds 6 entries, a clean axis top whose half is whole too
    expect(wrapper.findAll(".ytick").map((t) => t.text())).toEqual(["6", "3", "0"]);
    expect((wrapper.findAll(".stack")[1]!.element as HTMLElement).style.height).toBe("100%");
    expect(wrapper.findAll(".col")[1]!.findAll(".seg").map((s) => s.classes("cap"))).toEqual([false, false, true]);
  });

  it("lists the kinds it was given in the legend and nothing else", () => {
    expect(chart({ kinds: ["action", "error"] }).findAll(".legend li").map((l) => l.text())).toEqual(["Activity", "Errors"]);
  });

  it("reads a bucket with the arrow keys, for every kind at once", async () => {
    const wrapper = chart();
    const plot = wrapper.find(".plot");
    expect(wrapper.find(".tooltip").exists()).toBe(false);

    await plot.trigger("keydown", { key: "ArrowRight" });
    expect(wrapper.find(".tooltip .when").text()).toBe("Sat, Oct 3");
    await plot.trigger("keydown", { key: "ArrowRight" });

    expect(wrapper.find(".col.active").exists()).toBe(true);
    expect(wrapper.find(".tooltip .when").text()).toBe("Sun, Oct 4");
    expect(wrapper.findAll(".tooltip .line").map((l) => l.text())).toEqual(["2 Activity", "1 Errors", "3 Chat turns"]);

    await plot.trigger("keydown", { key: "Escape" });
    expect(wrapper.find(".tooltip").exists()).toBe(false);
  });

  it("stops at the ends, and ArrowLeft starts from the newest bucket", async () => {
    const wrapper = chart();
    const plot = wrapper.find(".plot");

    await plot.trigger("keydown", { key: "ArrowLeft" });
    expect(wrapper.find(".tooltip .when").text()).toBe("Mon, Oct 5");
    await plot.trigger("keydown", { key: "ArrowRight" });
    expect(wrapper.find(".tooltip .when").text()).toBe("Mon, Oct 5");
    await plot.trigger("keydown", { key: "Home" });
    expect(wrapper.find(".tooltip .when").text()).toBe("Sat, Oct 3");
  });

  it("has a table twin with the same numbers", async () => {
    const wrapper = chart();

    await wrapper.find(".head .chip").trigger("click");

    expect(wrapper.find(".plot").exists()).toBe(false);
    const rows = wrapper.findAll("tbody tr").map((r) => r.findAll("th, td").map((c) => c.text()));
    expect(rows[1]).toEqual(["Sun, Oct 4", "2", "1", "3"]);
    expect(wrapper.findAll("thead th").map((h) => h.text())).toEqual(["Day (UTC)", "Activity", "Errors", "Chat turns"]);
  });

  it("says so when there is nothing in the range, and dims while refetching", () => {
    const wrapper = chart({ series: series.slice(2), loading: true });

    expect(wrapper.find(".none").text()).toBe("No entries in this range.");
    expect(wrapper.find(".chart").classes()).toContain("dim");
  });

  it("labels only every few buckets on the time axis", () => {
    const hours = Array.from({ length: 24 }, (_, h) => ({
      bucket: `2026-10-05T${String(h).padStart(2, "0")}:00:00`,
      counts: { action: h },
    }));
    const wrapper = chart({ series: hours, kinds: ["action"], bucket: "hour" });

    expect(wrapper.findAll(".xtick").map((t) => t.text())).toEqual(["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"]);
  });
});

describe("BarList", () => {
  const items = [
    { key: "auth.login", label: "auth.login", count: 40 },
    { key: "backup.run", label: "backup.run", count: 10 },
  ];

  it("sizes each bar against the busiest row and writes the count at its tip", () => {
    const wrapper = mount(BarList, { props: { items, color: "red" } });

    expect(wrapper.findAll(".bar").map((b) => (b.element as HTMLElement).style.getPropertyValue("--share"))).toEqual(["1", "0.25"]);
    expect(wrapper.findAll(".value").map((v) => v.text())).toEqual(["40", "10"]);
    expect(wrapper.find("button").exists()).toBe(false);
  });

  it("emits the row's key when rows are selectable", async () => {
    const wrapper = mount(BarList, { props: { items, color: "red", selectable: true } });

    await wrapper.findAll("button")[1]!.trigger("click");

    expect(wrapper.emitted("select")).toEqual([["backup.run"]]);
  });

  it("does not emit when the rows are not selectable", async () => {
    const wrapper = mount(BarList, { props: { items, color: "red" } });

    await wrapper.find(".row").trigger("click");

    expect(wrapper.emitted("select")).toBeUndefined();
  });

  it("shows the empty text when there are no rows", () => {
    expect(mount(BarList, { props: { items: [], color: "red", emptyText: "No errors." } }).text()).toBe("No errors.");
  });
});

describe("HourHeatmap", () => {
  const cells = [
    { weekday: 1, hour: 13, count: 8 },
    { weekday: 0, hour: 20, count: 1 },
  ];

  it("is a full week by day, one cell per hour, plus the legend's swatches", () => {
    const wrapper = mount(HourHeatmap, { props: { cells } });

    expect(wrapper.findAll(".grid .cell")).toHaveLength(7 * 24);
    expect(wrapper.findAll(".grid .row:not(.ticks) .day").map((d) => d.text())).toEqual(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]);
    expect(wrapper.find(".grid").attributes("role")).toBe("img");
  });

  it("shades the busiest hour darkest and names each hour in its title", () => {
    const wrapper = mount(HourHeatmap, { props: { cells } });
    const byTitle = (title: string) => wrapper.findAll(".grid .cell").find((c) => c.attributes("title") === title)!;

    expect(byTitle("Mon 13:00 UTC: 8 entries").classes()).toContain("level-4");
    expect(byTitle("Sun 20:00 UTC: 1 entry").classes()).toContain("level-1");
    expect(byTitle("Tue 00:00 UTC: 0 entries").classes()).toContain("level-0");
  });
});

describe("KindStatTile", () => {
  const trend = [1, 2, 3];

  function tile(kind: "action" | "error" | "chat_trace", current: number, previous: number) {
    return mount(KindStatTile, { props: { kind, total: { current, previous }, trend, range: "7d" } });
  }

  it("shows the count, the change and the period it is against", () => {
    const wrapper = tile("action", 1500, 1000);

    expect(wrapper.find(".value").text()).toBe("1,500");
    expect(wrapper.find(".delta").text()).toBe("▲ +50% vs previous 7 days");
    expect(wrapper.find(".delta").classes()).not.toContain("bad");
    expect(wrapper.find("svg").exists()).toBe(true);
  });

  it("marks more errors, and only errors, as bad news", () => {
    expect(tile("error", 6, 3).find(".delta").classes()).toContain("bad");
    expect(tile("error", 2, 3).find(".delta").classes()).not.toContain("bad");
    expect(tile("chat_trace", 6, 3).find(".delta").classes()).not.toContain("bad");
  });

  it("says new, with no arrow, when there was nothing before", () => {
    expect(tile("chat_trace", 5, 0).find(".delta").text()).toBe("new vs previous 7 days");
  });
});
