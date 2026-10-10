import { describe, expect, it } from "vitest";
import { starterCopy } from "./starterCopy";

describe("starterCopy", () => {
  it("has a motto and a blurb for each shipped starter", () => {
    for (const id of ["guardian", "scout", "striker"]) {
      const copy = starterCopy(id);
      expect(copy.motto.length).toBeGreaterThan(0);
      expect(copy.blurb.length).toBeGreaterThan(0);
    }
    expect(starterCopy("guardian").motto).toBe("Endure. Protect. Prevail.");
  });

  it("falls back for a starter with no entry", () => {
    expect(starterCopy("newcomer")).toEqual(starterCopy(""));
  });
});
