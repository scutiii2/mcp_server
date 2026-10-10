import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient } from "../../api/EmberlingsClient";
import { CATALOG, PROFILE } from "../../api/EmberlingsClient.fixtures";
import { useEmberlingsStore } from "../../stores/emberlings";
import StarterPick from "./StarterPick.vue";

vi.mock("../../api/EmberlingsClient", () => ({ emberlingsClient: { createProfile: vi.fn() } }));

const client = vi.mocked(emberlingsClient);

beforeEach(() => {
  vi.resetAllMocks();
  setActivePinia(createPinia());
  useEmberlingsStore().catalog = CATALOG;
});

describe("StarterPick", () => {
  it("lists the starters as small cards and shows the first one in full", () => {
    const wrapper = mount(StarterPick);

    const choices = wrapper.findAll("[role=radio]");
    expect(choices.map((c) => c.attributes("aria-label"))).toEqual(["Guardian", "Striker"]);
    expect(choices.map((c) => c.attributes("aria-checked"))).toEqual(["true", "false"]);
    expect(choices[0]!.classes()).toContain("selected");
    expect(wrapper.find(".detail .spark-name").text()).toBe("Guardian");
    expect(wrapper.find(".detail .passive").exists()).toBe(true);
    expect(wrapper.find(".choice .passive").exists()).toBe(false);
    expect(wrapper.find("button.start").text()).toBe("Start with Guardian");
  });

  it("picking a small card glows it, shows it in full, and starts with it", async () => {
    client.createProfile.mockResolvedValue(PROFILE);
    const wrapper = mount(StarterPick);

    await wrapper.findAll("[role=radio]")[1]!.trigger("click");
    expect(wrapper.findAll("[role=radio]").map((c) => c.classes().includes("selected"))).toEqual([false, true]);
    expect(wrapper.find(".detail .spark-name").text()).toBe("Striker");
    expect(client.createProfile).not.toHaveBeenCalled();

    await wrapper.find("button.start").trigger("click");
    await flushPromises();

    expect(client.createProfile).toHaveBeenCalledExactlyOnceWith("striker");
    expect(wrapper.emitted("started")).toHaveLength(1);
  });

  it("starts with the first starter when none was clicked, and picks by keyboard", async () => {
    client.createProfile.mockResolvedValue(PROFILE);
    const wrapper = mount(StarterPick);

    await wrapper.findAll("[role=radio]")[1]!.trigger("keydown.enter");
    expect(wrapper.find("button.start").text()).toBe("Start with Striker");
    await wrapper.findAll("[role=radio]")[0]!.trigger("keydown.space");
    await wrapper.find("button.start").trigger("click");
    await flushPromises();

    expect(client.createProfile).toHaveBeenCalledExactlyOnceWith("guardian");
  });

  it("describes the chosen starter in the side panel and follows the pick", async () => {
    const wrapper = mount(StarterPick);

    expect(wrapper.find(".info .name").text()).toBe("Guardian");
    expect(wrapper.find(".info .blurb").text()).toBe("A steady shield for the journey ahead.");
    expect(wrapper.find(".info .facts").text()).toContain("100 HP · +5 / lvl");
    expect(wrapper.find(".info .facts").text()).toContain("Abilities unlock at levels 1 and 5.");
    expect(wrapper.find(".selected-label").text()).toBe("Selected");

    await wrapper.findAll("[role=radio]")[1]!.trigger("click");
    expect(wrapper.find(".info .name").text()).toBe("Striker");
    expect(wrapper.findAll(".selected-label")).toHaveLength(1);
  });

  it("goes back to the menu", async () => {
    const wrapper = mount(StarterPick);
    await wrapper.find("button.back").trigger("click");

    expect(wrapper.emitted("back")).toHaveLength(1);
  });
});
