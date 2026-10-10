import { flushPromises, mount, type DOMWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient, type EncounterPreview, type Profile } from "../../api/EmberlingsClient";
import { CATALOG, ENCOUNTER, PROFILE, battleView, ownedSpark } from "../../api/EmberlingsClient.fixtures";
import { useEmberlingsStore } from "../../stores/emberlings";
import EncounterPanel from "./EncounterPanel.vue";

vi.mock("../../api/EmberlingsClient", () => ({
  emberlingsClient: { rollEncounter: vi.fn(), declineEncounter: vi.fn(), startBattle: vi.fn(), profile: vi.fn() },
}));

const client = vi.mocked(emberlingsClient);

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
  client.profile.mockResolvedValue(PROFILE);
});

function mountPanel(profile: Profile = PROFILE, encounter: EncounterPreview | null = null) {
  const store = useEmberlingsStore();
  store.catalog = CATALOG;
  store.profile = profile;
  store.encounter = encounter;
  return { store, wrapper: mount(EncounterPanel) };
}

/** The first of `buttons` whose text is `text` (or matches it). */
function button(buttons: DOMWrapper<HTMLButtonElement>[], text: string | RegExp): DOMWrapper<HTMLButtonElement> {
  const found = buttons.find((b) => (typeof text === "string" ? b.text() === text : text.test(b.text())));
  if (!found) throw new Error(`no button ${String(text)}`);
  return found;
}

describe("EncounterPanel", () => {
  it("looks for a wild Spark once the cooldown is over", async () => {
    client.rollEncounter.mockResolvedValue(ENCOUNTER);
    const { store, wrapper } = mountPanel();

    const look = button(wrapper.findAll("button"), "Look for a wild Spark");
    expect(look.attributes("disabled")).toBeUndefined();
    await look.trigger("click");
    await flushPromises();

    expect(client.rollEncounter).toHaveBeenCalledOnce();
    expect(store.encounter?.id).toBe("e1");
    expect(wrapper.text()).toContain("A wild Bruiser");
  });

  it("waits out the cooldown with a countdown", () => {
    const { wrapper } = mountPanel({ ...PROFILE, next_roll_at: Date.now() / 1000 + 20 });

    const look = button(wrapper.findAll("button"), /Look again in/);
    expect(look.text()).toMatch(/Look again in 0:(19|20)/);
    expect(look.attributes("disabled")).toBeDefined();
  });

  it("declines for free", async () => {
    client.declineEncounter.mockResolvedValue({ ...ENCOUNTER, status: "declined" });
    const { store, wrapper } = mountPanel(PROFILE, ENCOUNTER);
    expect(wrapper.text()).toContain("Level 4");

    await button(wrapper.findAll("button"), "Decline").trigger("click");
    await flushPromises();

    expect(client.declineEncounter).toHaveBeenCalledExactlyOnceWith("e1");
    expect(store.encounter).toBeNull();
  });

  it("cannot fight while every Spark is fainted", () => {
    const { wrapper } = mountPanel(
      { ...PROFILE, sparks: [ownedSpark("guardian", { faint_until: Date.now() / 1000 + 600, fainted: true })] },
      ENCOUNTER,
    );

    expect(button(wrapper.findAll("button"), "Fight").attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("All your Sparks are fainted");
  });

  it("starts an autonomous battle only with a preset and an EMBLEM limit", async () => {
    client.startBattle.mockResolvedValue(battleView());
    const { wrapper } = mountPanel(PROFILE, ENCOUNTER);

    await button(wrapper.findAll("button"), "Fight").trigger("click");
    const form = wrapper.find("form.start-form");
    await button(form.findAll("button"), "Autonomous").trigger("click");
    const submit = form.find("button[type='submit']");
    expect(submit.attributes("disabled")).toBeDefined();
    expect(form.text()).toContain("Autonomous play needs a preset and an EMBLEM limit.");

    await form.find("select[name='preset']").setValue("2");
    await form.find("select[name='limit']").setValue("rare");
    expect(submit.attributes("disabled")).toBeUndefined();
    await form.trigger("submit");
    await flushPromises();

    expect(client.startBattle).toHaveBeenCalledExactlyOnceWith({
      encounter_id: "e1",
      spark_id: "guardian",
      preset_slot: 2,
      mode: "autonomous",
      emblem_limit: "rare",
    });
  });

  it("starts a manual battle with no preset and no limit", async () => {
    client.startBattle.mockResolvedValue(battleView({ mode: "manual" }));
    const { wrapper } = mountPanel(PROFILE, ENCOUNTER);

    await button(wrapper.findAll("button"), "Fight").trigger("click");
    await wrapper.find("form.start-form").trigger("submit");
    await flushPromises();

    expect(client.startBattle).toHaveBeenCalledExactlyOnceWith({
      encounter_id: "e1",
      spark_id: "guardian",
      preset_slot: null,
      mode: "manual",
      emblem_limit: null,
    });
  });
});
