import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient, type BattleView } from "../../api/EmberlingsClient";
import { CATALOG, PROFILE, battleView, fighter } from "../../api/EmberlingsClient.fixtures";
import { useEmberlingsStore } from "../../stores/emberlings";
import ActionBar from "./ActionBar.vue";
import BattleArena from "./BattleArena.vue";
import BattleControls from "./BattleControls.vue";
import BattleResult from "./BattleResult.vue";
import EmblemPrompt from "./EmblemPrompt.vue";
import RoundLog from "./RoundLog.vue";

vi.mock("../../api/EmberlingsClient", () => ({
  emberlingsClient: { action: vi.fn(), emblem: vi.fn(), setMode: vi.fn(), forfeit: vi.fn(), profile: vi.fn() },
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

function withBattle(view: BattleView) {
  const store = useEmberlingsStore();
  store.catalog = CATALOG;
  store.profile = PROFILE;
  store.battle = view;
  return store;
}

const manual = () =>
  battleView({
    mode: "manual",
    player: fighter("guardian", {
      abilities: [
        { id: "guardian_strike", name: "Strike", category: "ATTACK", percentage: 120, cooldown: 1, ready: true },
        { id: "guardian_rally", name: "Rally", category: "SUPPORT", percentage: 50, cooldown: 3, ready: false },
      ],
    }),
  });

describe("BattleArena", () => {
  it("shows both Sparks with their health written out, and what affects them", () => {
    const view = battleView({
      wild: fighter("bruiser", { hp: 20, buffs: [{ source: "bruiser_rally", stat: "essence", amount: 4, rounds_left: 2 }] }),
    });
    withBattle(view);

    const wrapper = mount(BattleArena, { props: { battle: view } });

    expect(wrapper.findAll("[role='progressbar']").map((m) => m.attributes("aria-valuenow"))).toEqual(["80", "20"]);
    expect(wrapper.findAll("p.hp").map((p) => p.text())).toEqual(["HP 80 / 100", "HP 20 / 100"]);
    expect(wrapper.text()).toContain("+4 essence, 2 rounds left");
    expect(wrapper.find(".versus").text()).toBe("VS");
  });
});

describe("RoundLog", () => {
  it("lists the rounds in words, latest first", () => {
    const view = battleView({
      history: [
        {
          round: 1,
          actions: { player: ["ability:guardian_strike", "ATTACK"], wild: ["attack", "ATTACK"] },
          events: [{ type: "attack", side: "player", damage: 18, protected: false, target_hp: 20 }],
        },
        {
          round: 2,
          actions: { player: ["attack", "ATTACK"], wild: ["attack", "ATTACK"] },
          events: [{ type: "attack", side: "wild", damage: 5, protected: false, target_hp: 75 }],
        },
      ],
    });
    withBattle(view);

    const wrapper = mount(RoundLog, { props: { battle: view } });

    const titles = wrapper.findAll(".title").map((t) => t.text());
    expect(titles[0]).toContain("R02");
    expect(titles[1]).toContain("Round 1: Guardian chose Strike, Bruiser chose Attack");
    expect(wrapper.text()).toContain("Guardian hits for 18; Bruiser has 20 HP left");
    expect(wrapper.find(".rounds").attributes("aria-live")).toBe("polite");
  });

  it("says when no round was played yet", () => {
    const view = battleView({ history: [] });
    withBattle(view);

    expect(mount(RoundLog, { props: { battle: view } }).text()).toContain("No rounds yet.");
  });
});

describe("ActionBar", () => {
  it("offers one button per legal action and shows abilities cooling down", () => {
    const view = manual();
    withBattle(view);

    const wrapper = mount(ActionBar, { props: { battle: view } });

    const buttons = wrapper.findAll("button.action");
    expect(buttons.map((b) => b.find(".action-name").text())).toEqual(["Attack", "Strike", "Flee", "Catch", "Rally"]);
    expect(buttons[1]!.attributes("disabled")).toBeUndefined();
    expect(buttons[4]!.attributes("disabled")).toBeDefined();
    expect(buttons[4]!.text()).toContain("Cooling down (3 rounds)");
  });

  it("sends the chosen action with the round and revision it saw", async () => {
    const view = manual();
    withBattle(view);
    client.action.mockResolvedValue(battleView({ mode: "manual", round: 2, revision: 2 }));
    const wrapper = mount(ActionBar, { props: { battle: view } });

    await wrapper.findAll("button.action")[1]!.trigger("click");
    await flushPromises();

    expect(client.action).toHaveBeenCalledExactlyOnceWith("b1", { round: 1, revision: 1 }, { kind: "ability", ability_id: "guardian_strike" });
  });

  it("asks which EMBLEM to throw for a catch", async () => {
    const view = manual();
    withBattle(view);
    client.action.mockResolvedValue(battleView({ mode: "manual", round: 2, revision: 2 }));
    const wrapper = mount(ActionBar, { props: { battle: view } });

    await wrapper.findAll("button.action")[3]!.trigger("click");
    expect(client.action).not.toHaveBeenCalled();
    await wrapper.findAll("button").find((b) => b.text() === "Normal (2)")!.trigger("click");
    await flushPromises();

    expect(client.action).toHaveBeenCalledExactlyOnceWith("b1", { round: 1, revision: 1 }, { kind: "catch", emblem_tier: "normal" });
  });
});

describe("BattleControls", () => {
  it("keeps a battle without an EMBLEM limit manual", async () => {
    const view = battleView({ mode: "manual", emblem_limit: null });
    withBattle(view);
    const wrapper = mount(BattleControls, { props: { battle: view } });

    const autonomous = wrapper.findAll("[role=tab]").find((b) => b.text() === "Autonomous")!;
    expect(autonomous.attributes("disabled")).toBeDefined();
    await autonomous.trigger("click");

    expect(client.setMode).not.toHaveBeenCalled();
  });

  it("switches to autonomous between rounds", async () => {
    const view = battleView({ mode: "manual" });
    withBattle(view);
    client.setMode.mockResolvedValue(battleView());
    const wrapper = mount(BattleControls, { props: { battle: view } });

    await wrapper.findAll("[role=tab]").find((b) => b.text() === "Autonomous")!.trigger("click");
    await flushPromises();

    expect(client.setMode).toHaveBeenCalledExactlyOnceWith("b1", { round: 1, revision: 1 }, "autonomous", null);
  });

  it("forfeits only after confirming", async () => {
    const view = manual();
    withBattle(view);
    client.forfeit.mockResolvedValue(
      battleView({ status: "terminal", phase: "terminal", result: { kind: "forfeited", faint_until: 1_700_000_600 } }),
    );
    const wrapper = mount(BattleControls, { props: { battle: view } });

    await wrapper.find("button.danger").trigger("click");
    expect(client.forfeit).not.toHaveBeenCalled();
    await wrapper.find("button.confirm").trigger("click");
    await flushPromises();

    expect(client.forfeit).toHaveBeenCalledExactlyOnceWith("b1");
  });
});

describe("EmblemPrompt", () => {
  const prompting = () =>
    battleView({
      phase: "awaiting_emblem",
      revision: 4,
      prompt: { deadline: 0, seconds_left: 5, permitted_tiers: ["normal"], owned: { normal: 2 } },
    });

  it("offers the permitted tiers with their counts while time is left", async () => {
    const store = withBattle(prompting());
    store.promptRemaining = 3.2;
    store.promptTotal = 5;
    client.emblem.mockResolvedValue(battleView({ mode: "manual", round: 2, revision: 5 }));
    const wrapper = mount(EmblemPrompt);

    expect(wrapper.find(".em-ring").text()).toBe("4s");
    expect(wrapper.text()).toContain("4 s left");
    await wrapper.findAll("button.tier").find((b) => b.text().startsWith("Normal"))!.trigger("click");
    await flushPromises();

    expect(client.emblem).toHaveBeenCalledExactlyOnceWith("b1", { round: 1, revision: 4 }, "normal");
  });

  it("disables the tiers at zero", () => {
    const store = withBattle(prompting());
    store.promptRemaining = 0;
    store.promptTotal = 5;

    const wrapper = mount(EmblemPrompt);

    expect(wrapper.text()).toContain("Time is up");
    expect(wrapper.findAll("button.tier").find((b) => b.text().startsWith("Normal"))!.attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("Your Spark will decide this turn.");
  });
});

describe("BattleResult", () => {
  it("shows a capture with the personalities it revealed, and Back leaves it", async () => {
    const view = battleView({
      status: "terminal",
      phase: "terminal",
      result: {
        kind: "captured",
        xp: 30,
        insignia: 12,
        level_before: 3,
        level_after: 4,
        spark_id: "bruiser",
        copies_granted: 2,
        copies: 2,
        tier_id: "rare",
        awarded_personality: { id: "w2", type: "BOLD", tier: 2 },
        revealed_personalities: [
          { id: "w1", type: "CAUTIOUS", tier: 1 },
          { id: "w2", type: "BOLD", tier: 2 },
        ],
      },
    });
    const store = withBattle(view);
    const wrapper = mount(BattleResult, { props: { battle: view } });

    const text = wrapper.text();
    expect(text).toContain("Captured");
    expect(wrapper.findAll(".reward")[0]!.text()).toBe("+30 XPfor Guardian, now level 4");
    expect(text).toContain("+12 Insignia");
    expect(wrapper.findAll(".reward")[2]!.text()).toBe("+2 copiesof Bruiser, now Rare");
    expect(text).toContain("Cautious · tier 1");
    expect(text).toContain("Bold · tier 2 (now yours)");

    await wrapper.findAll("button").find((b) => b.text() === "Back")!.trigger("click");
    await flushPromises();

    expect(store.battle).toBeNull();
    expect(client.profile).toHaveBeenCalledOnce();
  });

  it("says when the Spark fainted", () => {
    const view = battleView({ status: "terminal", phase: "terminal", result: { kind: "knocked_out", faint_until: 1_700_000_600 } });
    withBattle(view);

    const text = mount(BattleResult, { props: { battle: view } }).text();

    expect(text).toContain("Your Spark was knocked out");
    expect(text).toContain("Guardian fainted and needs rest before its next battle.");
  });
});
