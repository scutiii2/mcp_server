import { beforeEach, describe, expect, it, vi } from "vitest";
import { ascensionClient, newIdempotencyKey } from "./AscensionClient";
import { apiRequest } from "./http";

vi.mock("./http", () => ({ apiRequest: vi.fn() }));

const request = vi.mocked(apiRequest);
const KEY = { "Idempotency-Key": "k" };
const AT = { round: 3, revision: 7 };

beforeEach(() => {
  vi.clearAllMocks();
  request.mockResolvedValue({} as never);
});

describe("ascensionClient", () => {
  it("reads without a key and escapes ids", async () => {
    await ascensionClient.catalog();
    await ascensionClient.profile();
    await ascensionClient.encounter("e 1");
    await ascensionClient.battle("b1");
    await ascensionClient.preset("guardian", 2);
    await ascensionClient.personalities("guardian");
    await ascensionClient.personalities("guardian", 40, 50);

    expect(request.mock.calls).toEqual([
      ["GET", "/api/ascension/catalog"],
      ["GET", "/api/ascension/profile"],
      ["GET", "/api/ascension/encounters/e%201"],
      ["GET", "/api/ascension/battles/b1"],
      ["GET", "/api/ascension/ascendeds/guardian/presets/2"],
      ["GET", "/api/ascension/ascendeds/guardian/personalities"],
      ["GET", "/api/ascension/ascendeds/guardian/personalities?limit=50&cursor=40"],
    ]);
  });

  it("sends every change with the key it is given", async () => {
    await ascensionClient.createProfile("guardian", "k");
    await ascensionClient.savePreset("guardian", 1, ["p1"], "k");
    await ascensionClient.rollEncounter("k");
    await ascensionClient.declineEncounter("e1", "k");
    await ascensionClient.startBattle({ encounter_id: "e1", ascended_id: "guardian", preset_slot: null, mode: "manual", emblem_limit: null }, "k");
    await ascensionClient.action("b1", AT, { kind: "ability", ability_id: "guardian_strike" }, "k");
    await ascensionClient.emblem("b1", AT, "rare", "k");
    await ascensionClient.advance("b1", AT, "k");
    await ascensionClient.setMode("b1", AT, "autonomous", null, "k");
    await ascensionClient.setMode("b1", AT, "autonomous", "rare", "k");
    await ascensionClient.forfeit("b1", "k");
    await ascensionClient.buyEmblems("common", 3, "k");
    await ascensionClient.buyCopies("bruiser", "rare", "k");
    await ascensionClient.sellCopy("guardian", "k");
    await ascensionClient.resetProfile("k");

    expect(request.mock.calls).toEqual([
      ["POST", "/api/ascension/profile", { starter_ascended_id: "guardian" }, KEY],
      ["PUT", "/api/ascension/ascendeds/guardian/presets/1", { instance_ids: ["p1"] }, KEY],
      ["POST", "/api/ascension/encounters", undefined, KEY],
      ["POST", "/api/ascension/encounters/e1/decline", undefined, KEY],
      ["POST", "/api/ascension/battles", { encounter_id: "e1", ascended_id: "guardian", preset_slot: null, mode: "manual", emblem_limit: null }, KEY],
      ["POST", "/api/ascension/battles/b1/actions", { round: 3, revision: 7, action: { kind: "ability", ability_id: "guardian_strike" } }, KEY],
      ["POST", "/api/ascension/battles/b1/emblem", { round: 3, revision: 7, tier: "rare" }, KEY],
      ["POST", "/api/ascension/battles/b1/advance", { round: 3, revision: 7 }, KEY],
      ["POST", "/api/ascension/battles/b1/mode", { round: 3, revision: 7, mode: "autonomous" }, KEY],
      ["POST", "/api/ascension/battles/b1/mode", { round: 3, revision: 7, mode: "autonomous", emblem_limit: "rare" }, KEY],
      ["POST", "/api/ascension/battles/b1/forfeit", undefined, KEY],
      ["POST", "/api/ascension/shop/purchases", { kind: "emblem", tier: "common", quantity: 3 }, KEY],
      ["POST", "/api/ascension/shop/purchases", { kind: "copies", ascended_id: "bruiser", tier: "rare" }, KEY],
      ["POST", "/api/ascension/ascendeds/guardian/sales", undefined, KEY],
      ["POST", "/api/ascension/profile/reset", {}, KEY],
    ]);
  });

  it("makes a fresh key for each action when none is given", async () => {
    vi.spyOn(crypto, "randomUUID")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000001")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000002");

    await ascensionClient.rollEncounter();
    await ascensionClient.rollEncounter();

    expect(request.mock.calls.map((call) => call[3])).toEqual([
      { "Idempotency-Key": "00000000-0000-4000-8000-000000000001" },
      { "Idempotency-Key": "00000000-0000-4000-8000-000000000002" },
    ]);
  });

  it("makes a fresh key for each reset", async () => {
    vi.spyOn(crypto, "randomUUID")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000001")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000002");

    await ascensionClient.resetProfile();
    await ascensionClient.resetProfile();

    expect(request.mock.calls).toEqual([
      ["POST", "/api/ascension/profile/reset", {}, { "Idempotency-Key": "00000000-0000-4000-8000-000000000001" }],
      ["POST", "/api/ascension/profile/reset", {}, { "Idempotency-Key": "00000000-0000-4000-8000-000000000002" }],
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
