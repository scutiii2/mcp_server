import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { ascendedInfo } from "../../api/EmberlingsClient.fixtures";
import AscendedTemplateCard from "./AscendedTemplateCard.vue";

const striker = ascendedInfo("striker", {
  base: { hp: 100, essence: 30, speed: 20 },
  growth: { hp: 10, essence: 3, speed: 2 },
  passive: { kind: "low_hp_attack_bonus", params: { hp_below: 0.5, essence_fraction: 0.2 } },
});

describe("AscendedTemplateCard", () => {
  it("lays the name, level, stats, passive and abilities over the frame", () => {
    const wrapper = mount(AscendedTemplateCard, { props: { ascended: striker } });

    expect(wrapper.find(".ascended-name").text()).toBe("Striker");
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
    const wrapper = mount(AscendedTemplateCard, { props: { ascended: striker, level: 7, tierId: "rare" } });

    expect(wrapper.find(".level").text()).toBe("Lv 7");
    expect(wrapper.attributes("aria-label")).toBe("Striker, Rare, level 7");
  });

  it("keeps the passive's name and sentence in its tooltip, since the box cuts after four lines", () => {
    const wrapper = mount(AscendedTemplateCard, { props: { ascended: striker } });

    expect(wrapper.find(".passive").attributes("title")).toBe(
      "Low hp attack bonus: Below 50% HP, attacks deal extra damage equal to 20% of its Essence.",
    );
  });

  it("falls back to the passive's name for a kind it has no sentence for", () => {
    const wrapper = mount(AscendedTemplateCard, { props: { ascended: ascendedInfo("odd") } });

    expect(wrapper.find(".passive").text()).toBe("Steady");
  });

  it("tints the frame for every tier but Common", () => {
    const tintOf = (tierId: string) => {
      const tint = mount(AscendedTemplateCard, { props: { ascended: striker, tierId } }).find(".tint");
      return tint.exists() ? (tint.element as HTMLElement).style.background : null;
    };

    expect(tintOf("common")).toBeNull();
    expect(tintOf("unknown")).toBeNull();
    const tints = ["rare", "unique", "royal", "legendary", "forbidden"].map(tintOf);
    expect(tints.every((t) => t)).toBe(true);
    expect(new Set(tints).size).toBe(5);
  });

  it("shows the Ascended's portrait in the artwork window, or its letter when it has none", () => {
    const guardian = mount(AscendedTemplateCard, { props: { ascended: ascendedInfo("guardian") } });
    expect(guardian.find("img.portrait").exists()).toBe(true);
    expect(guardian.find(".letter").exists()).toBe(false);
    expect((guardian.find("img.portrait").element as HTMLElement).style.objectPosition).toBe("50% 21%");

    const bruiser = mount(AscendedTemplateCard, { props: { ascended: ascendedInfo("bruiser") } });
    expect(bruiser.find("img.portrait").exists()).toBe(false);
    expect(bruiser.find(".letter").text()).toBe("B");
  });

  it("the small card has a tier plate, no ability slots, and its own portrait focus", () => {
    const wrapper = mount(AscendedTemplateCard, { props: { ascended: ascendedInfo("sentinel"), tierId: "royal", compact: true } });

    expect(wrapper.find(".tier-plate").text()).toBe("Royal");
    expect(wrapper.find(".ability").exists()).toBe(false);
    expect(wrapper.findAll(".behind")).toHaveLength(1);
    expect((wrapper.find("img.portrait").element as HTMLElement).style.objectPosition).toBe("50% 14%");
  });

  it("colours each ability's slot by its category", () => {
    const ascended = ascendedInfo("mixed", {
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
    const wrapper = mount(AscendedTemplateCard, { props: { ascended } });

    const fills = wrapper.findAll(".behind:not(.art-fill)").map((el) => (el.element as HTMLElement).style.background);
    expect(fills).toHaveLength(3);
    expect(new Set(fills).size).toBe(3);
  });
});
