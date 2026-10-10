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
  it("lays the name, level, stats, passive and abilities over the frame", () => {
    const wrapper = mount(SparkTemplateCard, { props: { spark: striker } });

    expect(wrapper.find(".spark-name").text()).toBe("Striker");
    expect(wrapper.find(".level").text()).toBe("Lv 1");
    expect(wrapper.findAll(".stat").map((s) => s.text())).toEqual([
      expect.stringMatching(/HP\s*100\s*\+10 \/ lvl/),
      expect.stringMatching(/Essence\s*30\s*\+3 \/ lvl/),
      expect.stringMatching(/Speed\s*20\s*\+2 \/ lvl/),
    ]);
    expect(wrapper.find(".passive strong").text()).toBe("Low hp attack bonus");
    expect(wrapper.find(".passive").text()).toBe("Low hp attack bonus Below 50% HP, attacks deal extra damage equal to 20% of its Essence.");
    const abilities = wrapper.findAll(".ability");
    expect(abilities).toHaveLength(2);
    expect(abilities[0]!.text()).toContain("Strike");
    expect(abilities[0]!.text()).toContain("Attack 120% · cd 1");
    expect(abilities[1]!.find(".unlock").text()).toBe("Lv 5");
  });

  it("shows the level it is given and names the tier for assistive tech", () => {
    const wrapper = mount(SparkTemplateCard, { props: { spark: striker, level: 7, tierId: "rare" } });

    expect(wrapper.find(".level").text()).toBe("Lv 7");
    expect(wrapper.attributes("aria-label")).toBe("Striker, Rare, level 7");
  });

  it("keeps the passive's name and sentence in its tooltip, since the box cuts after four lines", () => {
    const wrapper = mount(SparkTemplateCard, { props: { spark: striker } });

    expect(wrapper.find(".passive").attributes("title")).toBe(
      "Low hp attack bonus: Below 50% HP, attacks deal extra damage equal to 20% of its Essence.",
    );
  });

  it("falls back to the passive's name for a kind it has no sentence for", () => {
    const wrapper = mount(SparkTemplateCard, { props: { spark: sparkInfo("odd") } });

    expect(wrapper.find(".passive").text()).toBe("Steady");
  });

  it("tints the frame for every tier but Normal", () => {
    const tintOf = (tierId: string) => {
      const tint = mount(SparkTemplateCard, { props: { spark: striker, tierId } }).find(".tint");
      return tint.exists() ? (tint.element as HTMLElement).style.background : null;
    };

    expect(tintOf("normal")).toBeNull();
    expect(tintOf("unknown")).toBeNull();
    const tints = ["rare", "legendary", "royalty", "ascended", "forbidden"].map(tintOf);
    expect(tints.every((t) => t)).toBe(true);
    expect(new Set(tints).size).toBe(5);
  });

  it("colours each ability's slot by its category", () => {
    const spark = sparkInfo("mixed", {
      abilities: ["ATTACK", "DEFENSE", "SUPPORT"].map((category, i) => ({
        id: `a${i}`,
        name: category,
        unlock_level: 1,
        category,
        percentage: 100,
        cooldown: 1,
        stat: null,
        duration: null,
      })),
    });
    const wrapper = mount(SparkTemplateCard, { props: { spark } });

    const fills = wrapper.findAll(".behind:not(.art-fill)").map((el) => (el.element as HTMLElement).style.background);
    expect(fills).toHaveLength(3);
    expect(new Set(fills).size).toBe(3);
  });
});
