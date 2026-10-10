import { describe, expect, it } from "vitest";
import { ascendedArt } from "./ascendedArt";

describe("ascendedArt", () => {
  it("has a portrait for each Ascended that has art, with its focus in range", () => {
    for (const id of ["guardian", "scout", "striker", "sentinel", "channeler", "forbidden"]) {
      const art = ascendedArt(id);
      expect(art, id).not.toBeNull();
      expect(art!.url).toBeTruthy();
      for (const focus of [art!.focus, art!.focusCompact]) {
        expect(focus).toBeGreaterThanOrEqual(0);
        expect(focus).toBeLessThanOrEqual(100);
      }
    }
  });

  it("returns null for an Ascended with no portrait yet", () => {
    expect(ascendedArt("bruiser")).toBeNull();
    expect(ascendedArt("")).toBeNull();
  });
});
