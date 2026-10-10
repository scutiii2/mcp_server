import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient, type BattleView, type EmblemPromptState } from "../api/EmberlingsClient";
import { ACCOUNT_WITH_EMBERLINGS, CATALOG, ENCOUNTER, PROFILE, battleView } from "../api/EmberlingsClient.fixtures";
import { ApiError } from "../api/http";
import { useAuthStore } from "./auth";
import { RECONNECT_MS, ROUND_PACE_MS, useEmberlingsStore } from "./emberlings";

vi.mock("../api/EmberlingsClient", () => ({
  emberlingsClient: {
    catalog: vi.fn(),
    profile: vi.fn(),
    createProfile: vi.fn(),
    personalities: vi.fn(),
    preset: vi.fn(),
    savePreset: vi.fn(),
    rollEncounter: vi.fn(),
    encounter: vi.fn(),
    declineEncounter: vi.fn(),
    startBattle: vi.fn(),
    battle: vi.fn(),
    action: vi.fn(),
    emblem: vi.fn(),
    advance: vi.fn(),
    setMode: vi.fn(),
    forfeit: vi.fn(),
    buyEmblems: vi.fn(),
    buyCopies: vi.fn(),
    sellCopy: vi.fn(),
    resetProfile: vi.fn(),
  },
}));

const client = vi.mocked(emberlingsClient);
// The server's deadline is deliberately nonsense: only seconds_left may count.
const PROMPT: EmblemPromptState = { deadline: 0, seconds_left: 5, permitted_tiers: ["normal"], owned: { normal: 2 } };

let visibility: DocumentVisibilityState = "visible";
let store: ReturnType<typeof useEmberlingsStore> | null = null;

beforeAll(() => {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
});

function setVisibility(state: DocumentVisibilityState): void {
  visibility = state;
  document.dispatchEvent(new Event("visibilitychange"));
}

async function attached(): Promise<ReturnType<typeof useEmberlingsStore>> {
  setActivePinia(createPinia());
  useAuthStore().account = ACCOUNT_WITH_EMBERLINGS;
  store = useEmberlingsStore();
  store.attach();
  await flushPromises();
  return store;
}

async function attachedWith(view: BattleView): Promise<ReturnType<typeof useEmberlingsStore>> {
  client.profile.mockResolvedValue({ ...PROFILE, active_battle: view.id });
  client.battle.mockResolvedValue(view);
  return attached();
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "performance"] });
  visibility = "visible";
  client.catalog.mockResolvedValue(CATALOG);
  client.profile.mockResolvedValue(PROFILE);
});

afterEach(() => {
  store?.detach();
  store = null;
  vi.useRealTimers();
});

describe("loading", () => {
  it("asks for a starter while there is no profile", async () => {
    client.profile.mockRejectedValue(new ApiError(404, "no profile yet; choose a starter first"));
    const s = await attached();

    expect(s.needsStarter).toBe(true);
    expect(s.profile).toBeNull();

    client.createProfile.mockResolvedValue(PROFILE);
    await s.createProfile("guardian");

    expect(client.createProfile).toHaveBeenCalledExactlyOnceWith("guardian");
    expect(s.profile).toEqual(PROFILE);
    expect(s.needsStarter).toBe(false);
  });

  it("restores a pending encounter instead of rolling a new one", async () => {
    client.profile.mockResolvedValue({ ...PROFILE, pending_encounter: "e1" });
    client.encounter.mockResolvedValue(ENCOUNTER);
    const s = await attached();

    expect(client.encounter).toHaveBeenCalledExactlyOnceWith("e1");
    expect(s.encounter?.id).toBe("e1");
    expect(client.rollEncounter).not.toHaveBeenCalled();
  });

  it("shows the page as unavailable on 502 and loads again on retry", async () => {
    client.catalog.mockRejectedValueOnce(new ApiError(502, "Emberlings is not available right now"));
    const s = await attached();

    expect(s.unavailable).toBe(true);

    await s.retry();

    expect(s.unavailable).toBe(false);
    expect(s.loaded).toBe(true);
  });

  it("forgets everything when the account changes", async () => {
    const s = await attachedWith(battleView());

    useAuthStore().account = { ...ACCOUNT_WITH_EMBERLINGS, id: 2 };
    await flushPromises();
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS * 3);

    expect(s.battle).toBeNull();
    expect(s.profile).toBeNull();
    expect(s.loaded).toBe(false);
    expect(client.advance).not.toHaveBeenCalled();
  });
});

describe("the autonomous loop", () => {
  it("plays a round every 1.5 s until the battle ends", async () => {
    const s = await attachedWith(battleView());
    client.advance
      .mockResolvedValueOnce(battleView({ round: 2, revision: 2 }))
      .mockResolvedValueOnce(
        battleView({ round: 3, revision: 3, status: "terminal", phase: "terminal", result: { kind: "won", xp: 5, insignia: 3 } }),
      );

    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS - 1);
    expect(client.advance).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(client.advance).toHaveBeenLastCalledWith("b1", { round: 1, revision: 1 });
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS);
    expect(client.advance).toHaveBeenLastCalledWith("b1", { round: 2, revision: 2 });
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS * 5);

    expect(client.advance).toHaveBeenCalledTimes(2);
    expect(s.battle?.result?.kind).toBe("won");
    // Loaded once, then again for the rewards.
    expect(client.profile).toHaveBeenCalledTimes(2);
  });

  it("stops when the page is left", async () => {
    const s = await attachedWith(battleView());

    s.detach();
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS * 5);

    expect(client.advance).not.toHaveBeenCalled();
  });

  it("pauses while the page is hidden and resumes from a fresh view", async () => {
    await attachedWith(battleView());

    setVisibility("hidden");
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS * 5);
    expect(client.advance).not.toHaveBeenCalled();

    client.battle.mockClear();
    setVisibility("visible");
    await flushPromises();
    expect(client.battle).toHaveBeenCalledExactlyOnceWith("b1");

    client.advance.mockResolvedValue(battleView({ mode: "manual", round: 2, revision: 2 }));
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS);
    expect(client.advance).toHaveBeenCalledTimes(1);
  });

  it("pauses on a network error and asks again every 3 s until it answers", async () => {
    const s = await attachedWith(battleView());
    client.advance.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS);
    expect(s.reconnecting).toBe(true);

    client.battle.mockClear();
    client.battle.mockRejectedValueOnce(new TypeError("Failed to fetch")).mockResolvedValueOnce(battleView({ round: 2, revision: 2 }));
    await vi.advanceTimersByTimeAsync(RECONNECT_MS);
    expect(client.battle).toHaveBeenCalledTimes(1);
    expect(s.reconnecting).toBe(true);
    await vi.advanceTimersByTimeAsync(RECONNECT_MS);
    expect(client.battle).toHaveBeenCalledTimes(2);
    expect(s.reconnecting).toBe(false);

    client.advance.mockResolvedValue(battleView({ mode: "manual", round: 3, revision: 3 }));
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS);
    expect(client.advance).toHaveBeenLastCalledWith("b1", { round: 2, revision: 2 });
  });

  it("stops and shows the page as unavailable on 502", async () => {
    const s = await attachedWith(battleView());
    client.advance.mockRejectedValue(new ApiError(502, "Emberlings is not available right now"));

    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS * 5);

    expect(s.unavailable).toBe(true);
    expect(client.advance).toHaveBeenCalledTimes(1);
  });
});

describe("manual play", () => {
  it("never advances on its own and does not retry a stale action", async () => {
    const s = await attachedWith(battleView({ mode: "manual" }));
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS * 5);
    expect(client.advance).not.toHaveBeenCalled();

    client.action.mockRejectedValue(new ApiError(409, "the battle moved on; reload it and try again"));
    client.battle.mockClear();
    client.battle.mockResolvedValue(battleView({ mode: "manual", round: 2, revision: 3 }));
    await s.act({ kind: "attack" });

    expect(client.action).toHaveBeenCalledExactlyOnceWith("b1", { round: 1, revision: 1 }, { kind: "attack" });
    expect(client.battle).toHaveBeenCalledExactlyOnceWith("b1");
    expect(s.battle?.revision).toBe(3);
    expect(s.error).toBe("the battle moved on; reload it and try again");
  });
});

describe("the EMBLEM prompt", () => {
  it("counts down on the local clock and lets the server settle it at zero", async () => {
    const s = await attachedWith(battleView({ phase: "awaiting_emblem", revision: 4, prompt: PROMPT }));

    expect(s.promptOpen).toBe(true);
    expect(s.promptRemaining).toBe(5);
    expect(s.promptTotal).toBe(5);

    await vi.advanceTimersByTimeAsync(2000);
    expect(s.promptRemaining).toBeCloseTo(3, 1);

    client.advance.mockResolvedValue(battleView({ round: 2, revision: 5 }));
    await vi.advanceTimersByTimeAsync(3000);

    expect(client.advance).toHaveBeenCalledExactlyOnceWith("b1", { round: 1, revision: 4 });
    expect(s.promptOpen).toBe(false);
  });

  it("throws the chosen EMBLEM before the time is up", async () => {
    const s = await attachedWith(battleView({ phase: "awaiting_emblem", revision: 4, prompt: PROMPT }));
    client.emblem.mockResolvedValue(battleView({ mode: "manual", round: 2, revision: 5 }));

    await s.answerEmblem("normal");
    await vi.advanceTimersByTimeAsync(6000);

    expect(client.emblem).toHaveBeenCalledExactlyOnceWith("b1", { round: 1, revision: 4 }, "normal");
    expect(client.advance).not.toHaveBeenCalled();
  });

  it("treats a late answer like an expired prompt: refresh and continue", async () => {
    const s = await attachedWith(battleView({ phase: "awaiting_emblem", revision: 4, prompt: PROMPT }));
    client.emblem.mockRejectedValue(new ApiError(409, "the prompt has expired; advance the battle instead"));
    client.battle.mockResolvedValue(
      battleView({ phase: "awaiting_emblem", revision: 4, prompt: { ...PROMPT, seconds_left: 0 } }),
    );
    client.advance.mockResolvedValue(battleView({ mode: "manual", round: 2, revision: 5 }));

    await s.answerEmblem("normal");
    await vi.advanceTimersByTimeAsync(0);

    expect(client.advance).toHaveBeenCalledExactlyOnceWith("b1", { round: 1, revision: 4 });
    expect(s.battle?.revision).toBe(5);
  });
});

describe("resetting progress", () => {
  it("clears profile, encounter and battle, asks for a starter and stops the loop", async () => {
    const s = await attachedWith(battleView({ mode: "autonomous" }));
    s.encounter = ENCOUNTER;
    client.resetProfile.mockResolvedValue({ reset: true });

    await expect(s.resetProgress()).resolves.toBe(true);

    expect(client.resetProfile).toHaveBeenCalledTimes(1);
    expect(s.profile).toBeNull();
    expect(s.encounter).toBeNull();
    expect(s.battle).toBeNull();
    expect(s.needsStarter).toBe(true);
    expect(s.busy).toBe(false);
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS * 5);
    expect(client.advance).not.toHaveBeenCalled();
  });

  it("keeps everything and says why when the server refuses", async () => {
    const s = await attached();
    client.resetProfile.mockRejectedValue(new ApiError(409, "finish or forfeit your battle before resetting"));

    await expect(s.resetProgress()).resolves.toBe(false);

    expect(s.error).toBe("finish or forfeit your battle before resetting");
    expect(s.profile).toEqual(PROFILE);
    expect(s.needsStarter).toBe(false);
    expect(s.busy).toBe(false);
  });

  it("keeps the autonomous loop running after a refused reset", async () => {
    const s = await attachedWith(battleView({ mode: "autonomous" }));
    client.resetProfile.mockRejectedValue(new ApiError(409, "finish or forfeit your battle before resetting"));
    client.advance.mockResolvedValue(battleView({ round: 2, revision: 2 }));

    await s.resetProgress();
    await vi.advanceTimersByTimeAsync(ROUND_PACE_MS);

    expect(client.advance).toHaveBeenCalledTimes(1);
    expect(s.battle).not.toBeNull();
  });

  it("marks the page unavailable on a 502 and keeps the state", async () => {
    const s = await attached();
    client.resetProfile.mockRejectedValue(new ApiError(502, "down"));

    await expect(s.resetProgress()).resolves.toBe(false);

    expect(s.unavailable).toBe(true);
    expect(s.profile).toEqual(PROFILE);
  });

  it("ignores a reset while another change is running", async () => {
    const s = await attached();
    let finish: (value: { reset: boolean }) => void = () => undefined;
    client.resetProfile.mockReturnValue(new Promise((resolve) => (finish = resolve)));

    const first = s.resetProgress();
    await expect(s.resetProgress()).resolves.toBe(false);
    expect(client.resetProfile).toHaveBeenCalledTimes(1);

    finish({ reset: true });
    await expect(first).resolves.toBe(true);
  });
});
