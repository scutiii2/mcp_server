import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import UsageHeatmap from "./UsageHeatmap.vue";

const TODAY = "2026-10-15";

function mountMap(daily: { date: string; tokens: number }[] = []) {
  return mount(UsageHeatmap, { props: { daily, today: TODAY } });
}

const cellFor = (wrapper: ReturnType<typeof mountMap>, date: string) =>
  wrapper.findAll(".heatmap .cell").find((c) => c.attributes("title")?.startsWith(date));

describe("UsageHeatmap", () => {
  it("draws one column per week and seven cells in each", () => {
    const wrapper = mountMap();

    expect(wrapper.findAll(".heatmap .week")).toHaveLength(53);
    expect(wrapper.findAll(".heatmap .week").every((w) => w.findAll(".cell").length === 7)).toBe(true);
  });

  it("is described for screen readers as a picture", () => {
    expect(mountMap().find(".heatmap").attributes("role")).toBe("img");
    expect(mountMap().find(".heatmap").attributes("aria-label")).toContain("12 months");
  });

  it("shades a day by how busy it was", () => {
    const wrapper = mountMap([
      { date: "2026-10-01", tokens: 1000 },
      { date: "2026-10-02", tokens: 100 },
    ]);

    expect(cellFor(wrapper, "2026-10-01")!.classes()).toContain("level-4");
    expect(cellFor(wrapper, "2026-10-02")!.classes()).toContain("level-1");
    expect(cellFor(wrapper, "2026-10-03")!.classes()).toContain("level-0");
  });

  it("names the day and its tokens when hovered", () => {
    const wrapper = mountMap([{ date: "2026-10-01", tokens: 12_345 }]);

    expect(cellFor(wrapper, "2026-10-01")!.attributes("title")).toBe(`2026-10-01: ${(12_345).toLocaleString()} tokens`);
  });

  it("leaves days that have not come yet blank, without a hover text", () => {
    const wrapper = mountMap();

    const future = wrapper.findAll(".heatmap .cell.future");
    expect(future).toHaveLength(2); // the Friday and Saturday after Thursday the 15th
    expect(future.every((c) => c.attributes("title") === undefined)).toBe(true);
  });

  it("has a legend from Less to More with all five shades", () => {
    const legend = mountMap().find(".legend");

    expect(legend.text()).toContain("Less");
    expect(legend.text()).toContain("More");
    expect(legend.findAll(".cell").map((c) => c.classes().find((k) => k.startsWith("level-")))).toEqual([
      "level-0",
      "level-1",
      "level-2",
      "level-3",
      "level-4",
    ]);
  });

  it("follows new data", async () => {
    const wrapper = mountMap();

    await wrapper.setProps({ daily: [{ date: "2026-10-01", tokens: 5 }] });

    expect(cellFor(wrapper, "2026-10-01")!.classes()).toContain("level-4");
  });
});
