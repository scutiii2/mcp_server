import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient } from "../api/EmberlingsClient";
import { ACCOUNT_WITH_EMBERLINGS, CATALOG, PROFILE, battleView } from "../api/EmberlingsClient.fixtures";
import { ApiError } from "../api/http";
import { useAuthStore } from "../stores/auth";
import EmberlingsView from "./EmberlingsView.vue";

vi.mock("../api/EmberlingsClient", () => ({
  emberlingsClient: {
    catalog: vi.fn(),
    profile: vi.fn(),
    createProfile: vi.fn(),
    battle: vi.fn(),
    encounter: vi.fn(),
    personalities: vi.fn(),
    preset: vi.fn(),
    advance: vi.fn(),
  },
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
  client.catalog.mockResolvedValue(CATALOG);
  client.profile.mockResolvedValue(PROFILE);
  client.personalities.mockResolvedValue({ items: [], next_cursor: null });
  client.preset.mockResolvedValue({ spark_id: "guardian", slot: 1, instance_ids: [] });
});

afterEach(() => {
  vi.useRealTimers();
});

async function mountView() {
  setActivePinia(createPinia());
  useAuthStore().account = ACCOUNT_WITH_EMBERLINGS;
  const wrapper = mount(EmberlingsView);
  await flushPromises();
  return wrapper;
}

type Wrapper = Awaited<ReturnType<typeof mountView>>;
const tab = (wrapper: Wrapper, label: string) => wrapper.findAll("button.segment").find((b) => b.text() === label)!;

describe("EmberlingsView", () => {
  it("a first visit opens the menu, then New game picks a starter and opens the collection", async () => {
    client.profile.mockRejectedValue(new ApiError(404, "no profile yet; choose a starter first"));
    const wrapper = await mountView();

    expect(wrapper.find("button.segment").exists()).toBe(false);
    expect(wrapper.findAll("nav .t").map((t) => t.text())).toEqual(["New game", "How to play"]);

    await wrapper.find("button.primary").trigger("click");
    expect(wrapper.text()).toContain("Choose your first Spark");
    expect(wrapper.findAll("[role=radio]").map((c) => c.attributes("aria-label"))).toEqual(["Guardian", "Striker"]);

    client.createProfile.mockResolvedValue(PROFILE);
    await wrapper.findAll("[role=radio]")[0]!.trigger("click");
    await wrapper.find("button.start").trigger("click");
    await flushPromises();

    expect(client.createProfile).toHaveBeenCalledExactlyOnceWith("guardian");
    expect(wrapper.findAll(".spark-card")).toHaveLength(1);
    expect(tab(wrapper, "Collection").classes()).toContain("active");
  });

  it("a returning player sees the menu first; Continue and Menu move between the screens", async () => {
    const wrapper = await mountView();

    expect(wrapper.find("button.segment").exists()).toBe(false);
    await wrapper.findAll("nav button")[0]!.trigger("click");
    expect(tab(wrapper, "Collection").classes()).toContain("active");

    await wrapper.find("button.chip").trigger("click");
    expect(wrapper.find("button.segment").exists()).toBe(false);
    await wrapper.findAll("nav button")[2]!.trigger("click");
    expect(tab(wrapper, "Shop").classes()).toContain("active");
  });

  it("shows Insignia and EMBLEM counts in the header", async () => {
    const wrapper = await mountView();
    await wrapper.findAll("nav button")[0]!.trigger("click");

    const wallet = wrapper.find(".wallet").text();
    expect(wallet).toContain("100");
    expect(wallet).toContain("Normal 2");
  });

  it("restores an active battle on the Battle tab instead of rolling", async () => {
    client.profile.mockResolvedValue({ ...PROFILE, active_battle: "b1" });
    client.battle.mockResolvedValue(battleView({ mode: "manual" }));
    const wrapper = await mountView();

    expect(tab(wrapper, "Battle").classes()).toContain("active");
    expect(wrapper.find(".arena").exists()).toBe(true);
    expect(wrapper.find(".action-bar").exists()).toBe(true);
  });

  it("replaces the page with a Retry when Emberlings is unavailable", async () => {
    client.catalog.mockRejectedValueOnce(new ApiError(502, "Emberlings is not available right now"));
    const wrapper = await mountView();

    expect(wrapper.find(".unavailable").text()).toContain("Emberlings is not available right now");
    expect(wrapper.find("nav").exists()).toBe(false);

    await wrapper.find(".unavailable button").trigger("click");
    await flushPromises();

    expect(wrapper.find(".unavailable").exists()).toBe(false);
    expect(wrapper.find("nav").exists()).toBe(true);
  });

  it("stops the battle loop when the page goes away", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "performance"] });
    client.profile.mockResolvedValue({ ...PROFILE, active_battle: "b1" });
    client.battle.mockResolvedValue(battleView());
    const wrapper = await mountView();

    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(10_000);

    expect(client.advance).not.toHaveBeenCalled();
  });
});
