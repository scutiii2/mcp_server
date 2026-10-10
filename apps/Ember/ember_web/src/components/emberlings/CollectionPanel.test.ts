import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient, type Profile } from "../../api/EmberlingsClient";
import { CATALOG, PROFILE, ownedSpark } from "../../api/EmberlingsClient.fixtures";
import { useEmberlingsStore } from "../../stores/emberlings";
import CollectionPanel from "./CollectionPanel.vue";
import PresetEditor from "./PresetEditor.vue";

vi.mock("../../api/EmberlingsClient", () => ({
  emberlingsClient: { personalities: vi.fn(), preset: vi.fn(), savePreset: vi.fn(), resetProfile: vi.fn() },
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
    expect(text).toContain("Guardian");
    expect(text).toContain("Rare");
    expect(text).toContain("3 copies");
    expect(text).toContain("40 / 300 XP");
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
    expect(text).toContain("Highest level reached");
    expect(text).toMatch(/Fainted · ready in 1:0[56]/);
  });

  it("opens a Spark's abilities, personalities (paged) and presets", async () => {
    client.personalities.mockResolvedValueOnce({ items: [{ id: "p1", type: "AGGRESSIVE", tier: 2 }], next_cursor: 7 });
    const wrapper = mountPanel();

    await wrapper.find(".spark-card").trigger("click");
    await flushPromises();

    expect(client.personalities).toHaveBeenCalledWith("guardian", null, 50);
    expect(client.preset).toHaveBeenCalledWith("guardian", 1);
    const details = wrapper.find(".details");
    expect(details.text()).toContain("Strike");
    expect(details.text()).toContain("Unlocks at level 5");
    expect(details.text()).toContain("Aggressive · tier 2");

    client.personalities.mockResolvedValueOnce({ items: [{ id: "p2", type: "CAUTIOUS", tier: 1 }], next_cursor: null });
    await details.findAll("button").find((b) => b.text() === "Show more")!.trigger("click");
    await flushPromises();

    expect(client.personalities).toHaveBeenLastCalledWith("guardian", 7, 50);
    expect(wrapper.find(".details").text()).toContain("Cautious · tier 1");
    expect(wrapper.find(".details").findAll("button").some((b) => b.text() === "Show more")).toBe(false);
  });
});

describe("reset progress", () => {
  const resetButton = (wrapper: ReturnType<typeof mountPanel>) =>
    wrapper.findAll("button").find((b) => b.classes().includes("reset-button"))!;

  it("is hidden without a profile", () => {
    const store = useEmberlingsStore();
    store.catalog = CATALOG;
    const wrapper = mount(CollectionPanel);

    expect(wrapper.find(".reset-button").exists()).toBe(false);
  });

  it("is disabled with a hint during a battle", () => {
    const wrapper = mountPanel({ ...PROFILE, active_battle: "b1" });

    expect((resetButton(wrapper).element as HTMLButtonElement).disabled).toBe(true);
    expect(wrapper.find(".reset").text()).toContain("Finish or forfeit your battle first");
  });

  it("needs RESET typed, then resets once and closes", async () => {
    client.resetProfile.mockResolvedValue({ reset: true });
    const wrapper = mountPanel();
    await resetButton(wrapper).trigger("click");

    const confirm = () => wrapper.find("button.confirm");
    expect((confirm().element as HTMLButtonElement).disabled).toBe(true);
    await wrapper.find(".require input").setValue("reset");
    expect((confirm().element as HTMLButtonElement).disabled).toBe(true);
    await confirm().trigger("click");
    expect(client.resetProfile).not.toHaveBeenCalled();

    await wrapper.find(".require input").setValue("RESET");
    expect((confirm().element as HTMLButtonElement).disabled).toBe(false);
    await confirm().trigger("click");
    await flushPromises();

    expect(client.resetProfile).toHaveBeenCalledTimes(1);
    expect(wrapper.findComponent({ name: "ConfirmModal" }).props("open")).toBe(false);
  });
});

describe("PresetEditor", () => {
  const items = ["p1", "p2", "p3", "p4"].map((id) => ({ id, type: "BOLD", tier: 1 }));

  it("equips at most three personalities and saves the preset", async () => {
    client.preset.mockResolvedValue({ spark_id: "guardian", slot: 1, instance_ids: ["p1"] });
    client.savePreset.mockResolvedValue({ spark_id: "guardian", slot: 1, instance_ids: ["p1", "p2", "p3"] });
    const wrapper = mount(PresetEditor, { props: { sparkId: "guardian", personalities: items } });
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

  it("loads the slot the user picks", async () => {
    const wrapper = mount(PresetEditor, { props: { sparkId: "guardian", personalities: items } });
    await flushPromises();

    await wrapper.findAll("button.segment").find((b) => b.text() === "Preset 3")!.trigger("click");
    await flushPromises();

    expect(client.preset).toHaveBeenLastCalledWith("guardian", 3);
  });
});
