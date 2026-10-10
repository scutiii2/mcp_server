import { describe, expect, it } from "vitest";
import { CATALOG } from "../api/EmberlingsClient.fixtures";
import { describeAction, describeEvent, formatCountdown, tierStanding, titleCase } from "./emberlings";

const NAMES = { player: "Guardian", wild: "Bruiser" };

describe("emberlings helpers", () => {
  it("draws the three strongest tiers as top and the one below as middle", () => {
    expect(CATALOG.tiers.map((t) => tierStanding(CATALOG.tiers, t.id))).toEqual(["low", "low", "middle", "top", "top", "top"]);
    expect(tierStanding(CATALOG.tiers, "unknown")).toBe("low");
  });

  it("writes ids as words", () => {
    expect(titleCase("knocked_out")).toBe("Knocked out");
    expect(titleCase("AGGRESSIVE")).toBe("Aggressive");
    expect(titleCase("rare")).toBe("Rare");
  });

  it("formats countdowns, rounding up", () => {
    expect(formatCountdown(4.2)).toBe("0:05");
    expect(formatCountdown(90)).toBe("1:30");
    expect(formatCountdown(3723)).toBe("1:02:03");
    expect(formatCountdown(-3)).toBe("0:00");
  });

  it("puts round-log events and actions in words", () => {
    expect(describeEvent({ type: "attack", side: "wild", damage: 12, protected: false, target_hp: 68 }, NAMES)).toBe(
      "Bruiser hits for 12; Guardian has 68 HP left",
    );
    expect(describeEvent({ type: "capture_attempt", side: "player", emblem: "rare", chance: 0.25, success: true }, NAMES)).toBe(
      "Guardian throws a Rare EMBLEM (25%): caught",
    );
    expect(describeEvent({ type: "order", first: "wild", chance_player_first: 0.4 }, NAMES)).toBe("Bruiser moves first");
    expect(describeEvent({ type: "something_new" }, NAMES)).toBe("Something new");
    expect(describeAction("ability:guardian_strike", [{ id: "guardian_strike", name: "Strike" }])).toBe("Strike");
    expect(describeAction("flee", [])).toBe("Flee");
  });
});
