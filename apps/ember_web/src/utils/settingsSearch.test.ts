import { describe, expect, it } from "vitest";
import { filterSettings, matchesQuery, type SearchableSetting } from "./settingsSearch";

const THEME: SearchableSetting = {
  label: "Theme",
  description: "Light, dark, or follow your system.",
  keywords: ["dark mode", "appearance"],
};
const CHIME: SearchableSetting = {
  label: "Chime when done",
  description: "Play a short sound when an answer arrives.",
  keywords: ["notification"],
};

describe("matchesQuery", () => {
  it("matches everything for an empty or blank query", () => {
    expect(matchesQuery(THEME, "")).toBe(true);
    expect(matchesQuery(THEME, "   ")).toBe(true);
  });

  it("matches the label, the description and the keywords, ignoring case", () => {
    expect(matchesQuery(THEME, "THEME")).toBe(true);
    expect(matchesQuery(THEME, "follow")).toBe(true);
    expect(matchesQuery(THEME, "appearance")).toBe(true);
  });

  it("needs every word, in any order", () => {
    expect(matchesQuery(THEME, "mode dark")).toBe(true);
    expect(matchesQuery(THEME, "dark chime")).toBe(false);
  });

  it("matches inside a word", () => {
    expect(matchesQuery(CHIME, "notif")).toBe(true);
  });

  it("works without keywords", () => {
    expect(matchesQuery({ label: "A", description: "b" }, "b")).toBe(true);
    expect(matchesQuery({ label: "A", description: "b" }, "z")).toBe(false);
  });
});

describe("filterSettings", () => {
  it("keeps the matching settings in their order", () => {
    expect(filterSettings([THEME, CHIME], "sound")).toEqual([CHIME]);
    expect(filterSettings([THEME, CHIME], "")).toEqual([THEME, CHIME]);
    expect(filterSettings([THEME, CHIME], "nothing here")).toEqual([]);
  });
});
