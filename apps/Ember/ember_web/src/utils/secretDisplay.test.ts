import { describe, expect, it } from "vitest";
import { groupText, segmentsOf, strengthOf } from "./secretDisplay";

describe("strengthOf", () => {
  it.each([
    [0, "weak", "Weak"],
    [44.9, "weak", "Weak"],
    [45, "fair", "Fair"],
    [69.9, "fair", "Fair"],
    [70, "strong", "Strong"],
    [99.9, "strong", "Strong"],
    [100, "excellent", "Excellent"],
    [300, "excellent", "Excellent"],
  ])("%s bits is %s", (bits, level, label) => {
    expect(strengthOf(bits)).toMatchObject({ level, label });
  });

  it("fills the bar up to 128 bits and never beyond", () => {
    expect(strengthOf(64).fraction).toBe(0.5);
    expect(strengthOf(128).fraction).toBe(1);
    expect(strengthOf(500).fraction).toBe(1);
    expect(strengthOf(-5).fraction).toBe(0);
  });
});

describe("groupText", () => {
  it("puts a space every N characters", () => {
    expect(groupText("123456", 3)).toBe("123 456");
    expect(groupText("12345678", 4)).toBe("1234 5678");
    expect(groupText("1234567", 3)).toBe("123 456 7");
  });

  it("leaves short text and nonsense sizes alone", () => {
    expect(groupText("12", 3)).toBe("12");
    expect(groupText("", 3)).toBe("");
    expect(groupText("123456", 0)).toBe("123456");
  });
});

describe("segmentsOf", () => {
  it("is one plain segment for a value with no letters (a PIN or a code)", () => {
    expect(segmentsOf("123 456")).toEqual([{ text: "123 456", kind: "plain" }]);
  });

  it("tags digits and symbols in a mixed value and merges runs", () => {
    expect(segmentsOf("ab12!!cd")).toEqual([
      { text: "ab", kind: "plain" },
      { text: "12", kind: "digit" },
      { text: "!!", kind: "symbol" },
      { text: "cd", kind: "plain" },
    ]);
  });

  it("is empty for empty text", () => {
    expect(segmentsOf("")).toEqual([]);
  });
});
