import { describe, expect, it } from "vitest";
import { CATALOG } from "../api/EmberlingsClient.fixtures";
import { abilityEffect, describeAction, describeEvent, formatCountdown, passiveText, tierStanding, titleCase } from "./emberlings";

const NAMES = { player: "Guardian", wild: "Bruiser" };

describe("passiveText and abilityEffect", () => {
  it("writes every shipped passive kind as a sentence", () => {
    expect(passiveText("defense_extension", { protected_attacks: 2, rounds: 2 })).toBe("Defense shields 2 attacks for 2 rounds.");
    expect(passiveText("defense_extension", {})).toBe("Defense shields 1 attack for 1 round.");
    expect(passiveText("low_hp_attack_bonus", { hp_below: 0.5, essence_fraction: 0.2 })).toBe(
      "Below 50% HP, attacks deal extra damage equal to 20% of its Essence.",
    );
    expect(passiveText("battle_start_speed", { essence_fraction: 0.5 })).toBe("At battle start, gains Speed equal to 50% of its Essence.");
    expect(passiveText("defense_rating_bonus", { essence_fraction: 0.5 })).toContain("50% of its Essence");
    expect(passiveText("attack_bonus_vs_defense", { essence_fraction: 0.25 })).toContain("25% of its Essence");
    expect(passiveText("support_duration_bonus", { rounds: 1 })).toBe("Support effects last 1 round longer.");
    expect(passiveText("cooldown_reduction", { rounds: 1, minimum: 1 })).toBe("Ability cooldowns are 1 round shorter, down to 1.");
  });

  it("falls back to the kind's name, and writes an ability's effect line", () => {
    expect(passiveText("something_new", {})).toBe("Something new");
    expect(abilityEffect({ category: "ATTACK", percentage: 150, cooldown: 1 })).toBe("Attack 150% · cd 1");
  });
});

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
