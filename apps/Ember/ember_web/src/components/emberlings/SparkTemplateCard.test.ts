import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { sparkInfo } from "../../api/EmberlingsClient.fixtures";
import SparkTemplateCard from "./SparkTemplateCard.vue";

const striker = sparkInfo("striker", {
  base: { hp: 100, essence: 30, speed: 20 },
  growth: { hp: 10, essence: 3, speed: 2 },
  passive: { kind: "low_hp_attack_bonus", params: { hp_below: 0.5, essence_fraction: 0.2 } },
});

describe("SparkTemplateCard", () => {
  it("lays out the header, stats, passive and abilities like the card template", () => {
    const wrapper = mount(SparkTemplateCard, { props: { spark: striker } });

    expect(wrapper.find(".spark-name").text()).toBe("Striker");
    expect(wrapper.find(".header-end").text()).toContain("Normal");
    expect(wrapper.find(".header-end").text()).toContain("Lv 1");
    expect(wrapper.findAll(".stat").map((s) => s.text())).toEqual([
      expect.stringMatching(/HP\s*100\s*\+10 \/ lvl/),
      expect.stringMatching(/Essence\s*30\s*\+3 \/ lvl/),
      expect.stringMatching(/Speed\s*20\s*\+2 \/ lvl/),
    ]);
    expect(wrapper.find(".passive").text()).toContain("Low hp attack bonus");
    expect(wrapper.find(".passive").text()).toContain("Below 50% HP, attacks deal extra damage equal to 20% of its Essence.");
    const abilities = wrapper.findAll(".ability");
    expect(abilities).toHaveLength(2);
    expect(abilities[0]!.text()).toContain("Strike");
    expect(abilities[0]!.text()).toContain("Attack 120% · cd 1");
    expect(abilities[1]!.find(".unlock").text()).toBe("Lv 5");
  });

  it("shows the level and tier it is given", () => {
    const wrapper = mount(SparkTemplateCard, { props: { spark: striker, level: 7, tierId: "rare" } });

    expect(wrapper.find(".header-end").text()).toContain("Rare");
    expect(wrapper.find(".header-end").text()).toContain("Lv 7");
  });

  it("keeps the whole passive sentence in its tooltip, since the box cuts it after five lines", () => {
    const wrapper = mount(SparkTemplateCard, { props: { spark: striker } });

    expect(wrapper.find(".passive span:not(.slot)").attributes("title")).toBe(
      "Below 50% HP, attacks deal extra damage equal to 20% of its Essence.",
    );
  });

  it("falls back to the passive's name for a kind it has no sentence for", () => {
    const wrapper = mount(SparkTemplateCard, { props: { spark: sparkInfo("odd") } });

    expect(wrapper.find(".passive").text()).toContain("Steady");
  });
});
