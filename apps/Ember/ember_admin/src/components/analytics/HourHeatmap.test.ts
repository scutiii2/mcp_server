import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import HourHeatmap from "./HourHeatmap.vue";

const show = () => mount(HourHeatmap, { props: { cells: [{ weekday: 1, hour: 13, count: 4 }] } });
const hour = (wrapper: ReturnType<typeof show>) => wrapper.get('[aria-label="Mon 13:00 UTC: 4 entries"]');

describe("HourHeatmap interactions", () => {
  it("immediately shows hour and count on hover, including empty hours", async () => {
    const wrapper = show();
    await hour(wrapper).trigger("pointerenter");
    expect(wrapper.get('[role="status"]').text()).toContain("Mon 13:00–14:00 UTC");
    expect(wrapper.get('[role="status"]').text()).toContain("4 entries");
    await hour(wrapper).trigger("pointerleave");
    expect(wrapper.get('[role="status"]').text()).toContain("Hover an hour");
    await wrapper.get('[aria-label="Sun 00:00 UTC: 0 entries"]').trigger("pointerenter");
    expect(wrapper.get('[role="status"]').text()).toContain("0 entries");
  });

  it("has no press feature: cells are not buttons and a click keeps nothing", async () => {
    const wrapper = show();
    expect(wrapper.find(".grid button").exists()).toBe(false);
    await hour(wrapper).trigger("click");
    await hour(wrapper).trigger("pointerleave");
    expect(wrapper.get('[role="status"]').text()).toContain("Hover an hour");
  });

  it("updates the hovered hour after refreshing the report", async () => {
    const wrapper = show();
    await hour(wrapper).trigger("pointerenter");
    await wrapper.setProps({ cells: [{ weekday: 1, hour: 13, count: 1 }] });
    expect(wrapper.get('[role="status"]').text()).toContain("1 entry");
  });
});
