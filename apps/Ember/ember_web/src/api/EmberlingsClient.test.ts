import { beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient, newIdempotencyKey } from "./EmberlingsClient";
import { apiRequest } from "./http";

vi.mock("./http", () => ({ apiRequest: vi.fn() }));

const request = vi.mocked(apiRequest);
const KEY = { "Idempotency-Key": "k" };
const AT = { round: 3, revision: 7 };

beforeEach(() => {
  vi.clearAllMocks();
  request.mockResolvedValue({} as never);
});

describe("emberlingsClient", () => {
  it("reads without a key and escapes ids", async () => {
    await emberlingsClient.catalog();
    await emberlingsClient.profile();
    await emberlingsClient.encounter("e 1");
    await emberlingsClient.battle("b1");
    await emberlingsClient.preset("guardian", 2);
    await emberlingsClient.personalities("guardian");
    await emberlingsClient.personalities("guardian", 40, 50);

    expect(request.mock.calls).toEqual([
      ["GET", "/api/emberlings/catalog"],
      ["GET", "/api/emberlings/profile"],
      ["GET", "/api/emberlings/encounters/e%201"],
      ["GET", "/api/emberlings/battles/b1"],
      ["GET", "/api/emberlings/ascendeds/guardian/presets/2"],
      ["GET", "/api/emberlings/ascendeds/guardian/personalities"],
      ["GET", "/api/emberlings/ascendeds/guardian/personalities?limit=50&cursor=40"],
    ]);
  });

  it("sends every change with the key it is given", async () => {
    await emberlingsClient.createProfile("guardian", "k");
    await emberlingsClient.savePreset("guardian", 1, ["p1"], "k");
    await emberlingsClient.rollEncounter("k");
    await emberlingsClient.declineEncounter("e1", "k");
    await emberlingsClient.startBattle({ encounter_id: "e1", ascended_id: "guardian", preset_slot: null, mode: "manual", emblem_limit: null }, "k");
    await emberlingsClient.action("b1", AT, { kind: "ability", ability_id: "guardian_strike" }, "k");
    await emberlingsClient.emblem("b1", AT, "rare", "k");
    await emberlingsClient.advance("b1", AT, "k");
    await emberlingsClient.setMode("b1", AT, "autonomous", null, "k");
    await emberlingsClient.setMode("b1", AT, "autonomous", "rare", "k");
    await emberlingsClient.forfeit("b1", "k");
    await emberlingsClient.buyEmblems("common", 3, "k");
    await emberlingsClient.buyCopies("bruiser", "rare", "k");
    await emberlingsClient.sellCopy("guardian", "k");
    await emberlingsClient.resetProfile("k");

    expect(request.mock.calls).toEqual([
      ["POST", "/api/emberlings/profile", { starter_ascended_id: "guardian" }, KEY],
      ["PUT", "/api/emberlings/ascendeds/guardian/presets/1", { instance_ids: ["p1"] }, KEY],
      ["POST", "/api/emberlings/encounters", undefined, KEY],
      ["POST", "/api/emberlings/encounters/e1/decline", undefined, KEY],
      ["POST", "/api/emberlings/battles", { encounter_id: "e1", ascended_id: "guardian", preset_slot: null, mode: "manual", emblem_limit: null }, KEY],
      ["POST", "/api/emberlings/battles/b1/actions", { round: 3, revision: 7, action: { kind: "ability", ability_id: "guardian_strike" } }, KEY],
      ["POST", "/api/emberlings/battles/b1/emblem", { round: 3, revision: 7, tier: "rare" }, KEY],
      ["POST", "/api/emberlings/battles/b1/advance", { round: 3, revision: 7 }, KEY],
      ["POST", "/api/emberlings/battles/b1/mode", { round: 3, revision: 7, mode: "autonomous" }, KEY],
      ["POST", "/api/emberlings/battles/b1/mode", { round: 3, revision: 7, mode: "autonomous", emblem_limit: "rare" }, KEY],
      ["POST", "/api/emberlings/battles/b1/forfeit", undefined, KEY],
      ["POST", "/api/emberlings/shop/purchases", { kind: "emblem", tier: "common", quantity: 3 }, KEY],
      ["POST", "/api/emberlings/shop/purchases", { kind: "copies", ascended_id: "bruiser", tier: "rare" }, KEY],
      ["POST", "/api/emberlings/ascendeds/guardian/sales", undefined, KEY],
      ["POST", "/api/emberlings/profile/reset", {}, KEY],
    ]);
  });

  it("makes a fresh key for each action when none is given", async () => {
    vi.spyOn(crypto, "randomUUID")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000001")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000002");

    await emberlingsClient.rollEncounter();
    await emberlingsClient.rollEncounter();

    expect(request.mock.calls.map((call) => call[3])).toEqual([
      { "Idempotency-Key": "00000000-0000-4000-8000-000000000001" },
      { "Idempotency-Key": "00000000-0000-4000-8000-000000000002" },
    ]);
  });

  it("makes a fresh key for each reset", async () => {
    vi.spyOn(crypto, "randomUUID")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000001")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000002");

    await emberlingsClient.resetProfile();
    await emberlingsClient.resetProfile();

    expect(request.mock.calls).toEqual([
      ["POST", "/api/emberlings/profile/reset", {}, { "Idempotency-Key": "00000000-0000-4000-8000-000000000001" }],
      ["POST", "/api/emberlings/profile/reset", {}, { "Idempotency-Key": "00000000-0000-4000-8000-000000000002" }],
    ]);
  });

  it("makes keys without randomUUID too (plain HTTP on a LAN address)", () => {
    const original = crypto.randomUUID;
    Object.defineProperty(crypto, "randomUUID", { configurable: true, value: undefined });
    try {
      const first = newIdempotencyKey();
      expect(first).toMatch(/^[0-9a-f]{32}$/);
      expect(newIdempotencyKey()).not.toBe(first);
    } finally {
      Object.defineProperty(crypto, "randomUUID", { configurable: true, value: original });
    }
  });
});
