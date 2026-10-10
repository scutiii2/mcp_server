import { describe, expect, it } from "vitest";
import { sparkArt } from "./sparkArt";

describe("sparkArt", () => {
  it("has a portrait for each Spark that has art, with its focus in range", () => {
    for (const id of ["guardian", "scout", "striker", "sentinel", "channeler", "forbidden"]) {
      const art = sparkArt(id);
      expect(art, id).not.toBeNull();
      expect(art!.url).toBeTruthy();
      for (const focus of [art!.focus, art!.focusCompact]) {
        expect(focus).toBeGreaterThanOrEqual(0);
        expect(focus).toBeLessThanOrEqual(100);
      }
    }
  });

  it("returns null for a Spark with no portrait yet", () => {
    expect(sparkArt("bruiser")).toBeNull();
    expect(sparkArt("")).toBeNull();
  });
});
