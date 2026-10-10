import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient, type Profile } from "../../api/EmberlingsClient";
import { CATALOG, PROFILE, ownedSpark } from "../../api/EmberlingsClient.fixtures";
import { useEmberlingsStore } from "../../stores/emberlings";
import CollectionPanel from "./CollectionPanel.vue";
import PresetEditor from "./PresetEditor.vue";

vi.mock("../../api/EmberlingsClient", () => ({
  emberlingsClient: { personalities: vi.fn(), preset: vi.fn(), savePreset: vi.fn() },
}));

const client = vi.mocked(emberlingsClient);

// jsdom has no <dialog> methods.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

beforeEach(() => {
  vi.resetAllMocks();
  setActivePinia(createPinia());
  client.personalities.mockResolvedValue({ items: [], next_cursor: null });
  client.preset.mockResolvedValue({ spark_id: "guardian", slot: 1, instance_ids: [] });
});

function mountPanel(profile: Profile = PROFILE) {
  const store = useEmberlingsStore();
  store.catalog = CATALOG;
  store.profile = profile;
  return mount(CollectionPanel);
}

describe("CollectionPanel", () => {
  it("shows a card per owned Spark and lists the others as not collected", () => {
    const wrapper = mountPanel({ ...PROFILE, sparks: [ownedSpark("guardian", { copies: 3, tier_id: "rare" })] });

    const cards = wrapper.findAll(".spark-card");
    expect(cards).toHaveLength(1);
    const text = cards[0]!.text();
    expect(cards[0]!.find(".em-tier").text()).toBe("Rare");
    expect(text).toContain("3 copies");
    expect(text).toContain("40 / 300 XP");
    expect(cards[0]!.find(".spark-name").text()).toBe("Guardian");
    expect(cards[0]!.find(".level").text()).toBe("Lv 3");
    expect(cards[0]!.find(".tint").exists()).toBe(true);
    expect(cards[0]!.find(".passive").exists()).toBe(false);
    expect(wrapper.findAll(".missing-spark").map((row) => row.find(".missing-name").text())).toEqual([
      "Striker",
      "Bruiser",
      "Forbidden",
    ]);
  });

  it("hides the XP bar at the level cap and counts a faint down", () => {
    const wrapper = mountPanel({
      ...PROFILE,
      sparks: [ownedSpark("guardian", { xp_needed: null, faint_until: Date.now() / 1000 + 65 })],
    });

    const text = wrapper.find(".spark-card").text();
    expect(text).toMatch(/Fainted, ready in 1:0[56]/);
    expect(wrapper.find(".spark-card .xp").exists()).toBe(false);
    expect(wrapper.find(".spark-card").classes()).toContain("down");
  });

  it("says Highest level reached at the cap", () => {
    const wrapper = mountPanel({ ...PROFILE, sparks: [ownedSpark("guardian", { xp_needed: null })] });

    expect(wrapper.find(".spark-card").text()).toContain("Highest level reached");
    expect(wrapper.find(".spark-card .em-bar").exists()).toBe(false);
  });

  it("opens a Spark's abilities, personalities (paged) and presets", async () => {
    client.personalities.mockResolvedValueOnce({ items: [{ id: "p1", type: "AGGRESSIVE", tier: 2 }], next_cursor: 7 });
    const wrapper = mountPanel();

    await wrapper.find(".spark-card").trigger("click");
    await flushPromises();

    expect(client.personalities).toHaveBeenCalledWith("guardian", null, 50);
    expect(client.preset).toHaveBeenCalledWith("guardian", 1);
    const details = wrapper.find(".details");
    expect(details.find(".big-card .spark-name").text()).toBe("Guardian");
    expect(details.findAll(".big-card .ability").map((a) => a.find("strong").text())).toEqual(["Strike", "Rally"]);
    expect(details.find(".personalities").text()).toContain("Aggressive");
    expect(details.find(".personalities").text()).toContain("Tier 2");
    expect(details.text()).toContain("1+ collected");

    client.personalities.mockResolvedValueOnce({ items: [{ id: "p2", type: "CAUTIOUS", tier: 1 }], next_cursor: null });
    await details.findAll("button").find((b) => b.text() === "Show more")!.trigger("click");
    await flushPromises();

    expect(client.personalities).toHaveBeenLastCalledWith("guardian", 7, 50);
    expect(wrapper.find(".personalities").text()).toContain("Cautious");
    expect(wrapper.find(".details").findAll("button").some((b) => b.text() === "Show more")).toBe(false);
  });
});

describe("not collected", () => {
  it("shows a face-down card with the Spark's name and how to get it", () => {
    const wrapper = mountPanel();

    const rows = wrapper.findAll(".missing-spark");
    expect(rows[0]!.find("img.back").exists()).toBe(true);
    expect(rows[0]!.text()).toContain("Catch one, or buy copies in the shop");
    expect(rows[rows.length - 1]!.text()).toContain("Only by capture");
  });
});

describe("PresetEditor", () => {
  const items = ["p1", "p2", "p3", "p4"].map((id) => ({ id, type: "BOLD", tier: 1 }));

  it("equips at most three personalities and saves the preset", async () => {
    client.preset.mockResolvedValue({ spark_id: "guardian", slot: 1, instance_ids: ["p1"] });
    client.savePreset.mockResolvedValue({ spark_id: "guardian", slot: 1, instance_ids: ["p1", "p2", "p3"] });
    const wrapper = mount(PresetEditor, { props: { sparkId: "guardian", sparkName: "Guardian", personalities: items } });
    await flushPromises();

    const switches = wrapper.findAll("input[role='switch']");
    expect(switches.map((s) => (s.element as HTMLInputElement).checked)).toEqual([true, false, false, false]);
    await switches[1]!.setValue(true);
    await switches[2]!.setValue(true);
    expect((switches[3]!.element as HTMLInputElement).disabled).toBe(true);

    await wrapper.findAll("button").find((b) => b.text() === "Save preset")!.trigger("click");
    await flushPromises();

    expect(client.savePreset).toHaveBeenCalledExactlyOnceWith("guardian", 1, ["p1", "p2", "p3"]);
  });

  it("announces the save in a toast and keeps the saved state", async () => {
    client.preset.mockResolvedValue({ spark_id: "guardian", slot: 1, instance_ids: [] });
    client.savePreset.mockResolvedValue({ spark_id: "guardian", slot: 1, instance_ids: ["p1"] });
    const wrapper = mount(PresetEditor, { props: { sparkId: "guardian", sparkName: "Guardian", personalities: items } });
    await flushPromises();

    await wrapper.findAll("input[role='switch']")[0]!.setValue(true);
    expect(wrapper.find(".count").text()).toBe("Preset 1 · 1 of 3 personalities equipped");
    await wrapper.find("button.save").trigger("click");
    await flushPromises();

    expect(wrapper.find(".em-toast").text()).toBe("Preset 1 saved. Guardian is ready.");
    expect((wrapper.find("button.save").element as HTMLButtonElement).disabled).toBe(true);
  });

  it("loads the slot the user picks", async () => {
    const wrapper = mount(PresetEditor, { props: { sparkId: "guardian", sparkName: "Guardian", personalities: items } });
    await flushPromises();

    await wrapper.findAll("[role=tab]").find((b) => b.text() === "3")!.trigger("click");
    await flushPromises();

    expect(client.preset).toHaveBeenLastCalledWith("guardian", 3);
  });
});
