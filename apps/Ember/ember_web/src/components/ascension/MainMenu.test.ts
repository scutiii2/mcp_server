import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ascensionClient, type Profile } from "../../api/AscensionClient";
import { CATALOG, PROFILE } from "../../api/AscensionClient.fixtures";
import { useAscensionStore } from "../../stores/ascension";
import MainMenu from "./MainMenu.vue";

vi.mock("../../api/AscensionClient", () => ({ ascensionClient: { resetProfile: vi.fn() } }));

const client = vi.mocked(ascensionClient);

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
});

function mountMenu(profile: Profile | null = PROFILE) {
  const store = useAscensionStore();
  store.catalog = CATALOG;
  store.profile = profile;
  return mount(MainMenu);
}

const labels = (wrapper: ReturnType<typeof mountMenu>) => wrapper.findAll("nav .label").map((t) => t.text());

describe("MainMenu", () => {
  it("offers only New game and How to play without a save", async () => {
    const wrapper = mountMenu(null);

    expect(labels(wrapper)).toEqual(["New game", "How to play"]);
    expect(wrapper.find(".save").text()).toBe("Three Ascended. Your first choice.");
    expect(wrapper.find(".hand-caption").text()).toBe("Guardian · Striker");
    await wrapper.find("button.primary").trigger("click");
    expect(wrapper.emitted("newGame")).toHaveLength(1);
  });

  it("offers Continue, Quick battle and Shop with a save, and shows the stats", async () => {
    const wrapper = mountMenu();

    expect(labels(wrapper)).toEqual(["Continue", "Quick battle", "Shop", "How to play", "Reset progress"]);
    expect(wrapper.find(".save").text()).toBe("1 Ascended, 100 Insignia");
    expect(wrapper.find(".hand-caption").text()).toBe("Your first Ascended");
    const buttons = wrapper.findAll("nav button");
    await buttons[0]!.trigger("click");
    await buttons[1]!.trigger("click");
    await buttons[2]!.trigger("click");
    expect(wrapper.emitted("play")).toEqual([["collection"], ["battle"], ["shop"]]);
  });

  it("previews the starters without a save and shows your team with one", () => {
    const names = (w: ReturnType<typeof mountMenu>) => w.findAll(".ascended .ascended-name").map((n) => n.text());

    expect(names(mountMenu(null))).toEqual(["Guardian", "Striker"]);
    const team = mountMenu();
    expect(names(team)).toEqual(["Guardian"]);
    expect(team.find(".ascended .level").text()).toBe("Lv 3");
    expect(mountMenu(null).find(".ascended .level").exists()).toBe(false);
  });

  it("opens How to play in a dialog", async () => {
    const wrapper = mountMenu(null);
    await wrapper.findAll("nav button")[1]!.trigger("click");

    const help = wrapper.findAllComponents({ name: "EmDialog" }).find((m) => m.props("title") === "Keep the fire going");
    expect(help?.props("open")).toBe(true);
    expect(wrapper.find(".rules").exists()).toBe(true);
  });
});

describe("reset progress", () => {
  const resetButton = (wrapper: ReturnType<typeof mountMenu>) => wrapper.find("button.danger");

  it("is disabled with a hint during a battle", () => {
    const wrapper = mountMenu({ ...PROFILE, active_battle: "b1" });

    expect((resetButton(wrapper).element as HTMLButtonElement).disabled).toBe(true);
    expect(wrapper.text()).toContain("Finish or forfeit your battle to reset");
  });

  it("needs RESET typed, then resets once and closes", async () => {
    client.resetProfile.mockResolvedValue({ reset: true });
    const wrapper = mountMenu();
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
    expect(wrapper.findComponent({ name: "EmConfirm" }).props("open")).toBe(false);
    expect(labels(wrapper)).toEqual(["New game", "How to play"]);
  });
});
