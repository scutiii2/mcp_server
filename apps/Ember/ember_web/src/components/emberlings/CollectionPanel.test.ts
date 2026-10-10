import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient, type Profile } from "../../api/EmberlingsClient";
import { CATALOG, PROFILE, ownedAscended, ascendedInfo } from "../../api/EmberlingsClient.fixtures";
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
  client.preset.mockResolvedValue({ ascended_id: "guardian", slot: 1, instance_ids: [] });
});

function mountPanel(profile: Profile = PROFILE) {
  const store = useEmberlingsStore();
  store.catalog = CATALOG;
  store.profile = profile;
  return mount(CollectionPanel);
}

describe("CollectionPanel", () => {
  it("shows a card per owned Ascended and lists the others as not collected", () => {
    const wrapper = mountPanel({ ...PROFILE, ascendeds: [ownedAscended("guardian", { copies: 3, tier_id: "rare" })] });

    const cards = wrapper.findAll(".ascended-card");
    expect(cards).toHaveLength(1);
    const text = cards[0]!.text();
    expect(cards[0]!.find(".em-tier").text()).toBe("Rare");
    expect(text).toContain("3 copies");
    expect(text).toContain("40 / 300 XP");
    expect(cards[0]!.find(".ascended-name").text()).toBe("Guardian");
    expect(cards[0]!.find(".level").text()).toBe("Lv 3");
    expect(cards[0]!.find(".tint").exists()).toBe(true);
    expect(cards[0]!.find(".passive").exists()).toBe(false);
    expect(wrapper.findAll(".missing-ascended").map((row) => row.find(".missing-name").text())).toEqual([
      "Striker",
      "Bruiser",
      "Forbidden",
    ]);
  });

  it("hides the XP bar at the level cap and counts a faint down", () => {
    const wrapper = mountPanel({
      ...PROFILE,
      ascendeds: [ownedAscended("guardian", { xp_needed: null, faint_until: Date.now() / 1000 + 65 })],
    });

    const text = wrapper.find(".ascended-card").text();
    expect(text).toMatch(/Fainted, ready in 1:0[56]/);
    expect(wrapper.find(".ascended-card .xp").exists()).toBe(false);
    expect(wrapper.find(".ascended-card").classes()).toContain("down");
  });

  it("says Highest level reached at the cap", () => {
    const wrapper = mountPanel({ ...PROFILE, ascendeds: [ownedAscended("guardian", { xp_needed: null })] });

    expect(wrapper.find(".ascended-card").text()).toContain("Highest level reached");
    expect(wrapper.find(".ascended-card .em-bar").exists()).toBe(false);
  });

  it("opens an Ascended's abilities, personalities (paged) and presets", async () => {
    client.personalities.mockResolvedValueOnce({ items: [{ id: "p1", type: "AGGRESSIVE", tier: 2 }], next_cursor: 7 });
    const wrapper = mountPanel();

    await wrapper.find(".ascended-card").trigger("click");
    await flushPromises();

    expect(client.personalities).toHaveBeenCalledWith("guardian", null, 50);
    expect(client.preset).toHaveBeenCalledWith("guardian", 1);
    const details = wrapper.find(".details");
    expect(details.find(".big-card .ascended-name").text()).toBe("Guardian");
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
  it("shows a face-down card with the Ascended's name and how to get it", () => {
    const wrapper = mountPanel();

    const rows = wrapper.findAll(".missing-ascended");
    expect(rows[0]!.find("img.back").exists()).toBe(true);
    expect(rows[0]!.text()).toContain("Catch one, or buy copies in the shop");
    expect(rows[rows.length - 1]!.text()).toContain("Only by capture");
  });
});

describe("PresetEditor", () => {
  const items = ["p1", "p2", "p3", "p4"].map((id) => ({ id, type: "BOLD", tier: 1 }));

  it("equips at most three personalities and saves the preset", async () => {
    client.preset.mockResolvedValue({ ascended_id: "guardian", slot: 1, instance_ids: ["p1"] });
    client.savePreset.mockResolvedValue({ ascended_id: "guardian", slot: 1, instance_ids: ["p1", "p2", "p3"] });
    const wrapper = mount(PresetEditor, { props: { ascendedId: "guardian", ascendedName: "Guardian", personalities: items } });
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
    client.preset.mockResolvedValue({ ascended_id: "guardian", slot: 1, instance_ids: [] });
    client.savePreset.mockResolvedValue({ ascended_id: "guardian", slot: 1, instance_ids: ["p1"] });
    const wrapper = mount(PresetEditor, { props: { ascendedId: "guardian", ascendedName: "Guardian", personalities: items } });
    await flushPromises();

    await wrapper.findAll("input[role='switch']")[0]!.setValue(true);
    expect(wrapper.find(".count").text()).toBe("Preset 1 · 1 of 3 personalities equipped");
    await wrapper.find("button.save").trigger("click");
    await flushPromises();

    expect(wrapper.find(".em-toast").text()).toBe("Preset 1 saved. Guardian is ready.");
    expect((wrapper.find("button.save").element as HTMLButtonElement).disabled).toBe(true);
  });

  it("loads the slot the user picks", async () => {
    const wrapper = mount(PresetEditor, { props: { ascendedId: "guardian", ascendedName: "Guardian", personalities: items } });
    await flushPromises();

    await wrapper.findAll("[role=tab]").find((b) => b.text() === "3")!.trigger("click");
    await flushPromises();

    expect(client.preset).toHaveBeenLastCalledWith("guardian", 3);
  });

  describe("Ascension Types", () => {
    const TYPED = {
      ...CATALOG,
      ascendeds: [
        ascendedInfo("guardian", { starter: true, ascension_types: ["enchant"] }),
        ascendedInfo("striker", { starter: true, ascension_types: ["divine", "enchant"] }),
        ascendedInfo("bruiser", { ascension_types: [] }),
        ascendedInfo("forbidden", { forbidden: true, ascension_types: ["abyss"] }),
      ],
    };
    const PROFILE_TYPED: Profile = {
      ...PROFILE,
      ascendeds: [
        ownedAscended("guardian", { ascension_types: ["enchant"] }),
        ownedAscended("striker", { ascension_types: ["divine", "enchant"] }),
        ownedAscended("bruiser", { ascension_types: [] }),
      ],
    };

    function mountTyped() {
      const wrapper = mountPanel(PROFILE_TYPED);
      useEmberlingsStore().catalog = TYPED;
      return wrapper;
    }
    const chip = (wrapper: ReturnType<typeof mountTyped>, label: string) => wrapper.findAll(".chip").find((c) => c.text() === label)!;
    const names = (wrapper: ReturnType<typeof mountTyped>) => wrapper.findAll(".ascended-card .ascended-name").map((n) => n.text());

    it("offers a chip per type in the catalog and starts with All", async () => {
      const wrapper = mountTyped();
      await flushPromises();
      expect(wrapper.findAll(".chip").map((c) => c.text())).toEqual(["All", "Abyss", "Divine", "Enchant"]);
      expect(chip(wrapper, "All").attributes("aria-pressed")).toBe("true");
      expect(names(wrapper)).toEqual(["Guardian", "Striker", "Bruiser"]);
    });

    it("filters owned and not-collected cards by one type, and a second click clears it", async () => {
      const wrapper = mountTyped();
      await chip(wrapper, "Enchant").trigger("click");
      expect(names(wrapper)).toEqual(["Guardian", "Striker"]);
      expect(wrapper.findAll(".missing-ascended")).toHaveLength(0);
      await chip(wrapper, "Abyss").trigger("click");
      expect(wrapper.find(".empty").text()).toBe("No Abyss Ascended collected yet.");
      expect(wrapper.findAll(".missing-name").map((n) => n.text())).toEqual(["Forbidden"]);
      await chip(wrapper, "Abyss").trigger("click");
      expect(chip(wrapper, "All").attributes("aria-pressed")).toBe("true");
    });

    it("groups owned cards by type when the switch is on", async () => {
      const wrapper = mountTyped();
      await wrapper.find("input[role=switch]").setValue(true);
      const groups = wrapper.findAll(".group").map((g) => [g.find(".group-name").text(), g.findAll(".ascended-name").map((n) => n.text())]);
      expect(groups).toEqual([
        ["Divine 1", ["Striker"]],
        ["Enchant 2", ["Guardian", "Striker"]],
        ["No type 1", ["Bruiser"]],
      ]);
    });
  });
});
