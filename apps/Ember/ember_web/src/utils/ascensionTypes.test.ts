import { describe, expect, it } from "vitest";
import { filterByType, groupByType, typeLabel, typesPresent } from "./ascensionTypes";

const item = (name: string, ...types: string[]) => ({ name, ascension_types: types });
const ITEMS = [item("a", "enchant"), item("b", "divine", "enchant"), item("c"), item("d", "pure")];

describe("Ascension Types helpers", () => {
  it("names a type, falling back to a capitalised id", () => {
    expect(typeLabel("abyss")).toBe("Abyss");
    expect(typeLabel("mystic")).toBe("Mystic");
  });

  it("lists the types present in display order", () => {
    expect(typesPresent(ITEMS)).toEqual(["pure", "divine", "enchant"]);
    expect(typesPresent([item("x", "mystic", "pure")])).toEqual(["pure", "mystic"]);
  });

  it("filters by one type, or returns everything", () => {
    expect(filterByType(ITEMS, "enchant").map((i) => i.name)).toEqual(["a", "b"]);
    expect(filterByType(ITEMS, null)).toHaveLength(4);
    expect(filterByType(ITEMS, "abyss")).toEqual([]);
  });

  it("groups by type: several types means several groups, none goes last", () => {
    const groups = groupByType(ITEMS);
    expect(groups.map((g) => [g.label, g.items.map((i) => i.name)])).toEqual([
      ["Pure", ["d"]],
      ["Divine", ["b"]],
      ["Enchant", ["a", "b"]],
      ["No type", ["c"]],
    ]);
    expect(groups.at(-1)!.typeId).toBeNull();
  });
});
