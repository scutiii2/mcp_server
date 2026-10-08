import { describe, expect, it } from "vitest";
import type { NavPrefs } from "../api/NavPreferencesClient";
import { arrange, dropPage, EMPTY_PREFS, isDefault, railPages, setHidden, setPinned } from "./navArrangement";

const PAGES = ["/a", "/b", "/c", "/d"].map((to) => ({ to }));
const ids = (list: { to: string }[]) => list.map((p) => p.to);
const prefs = (p: Partial<NavPrefs>): NavPrefs => ({ ...EMPTY_PREFS, ...p });

describe("arrange", () => {
  it("keeps the default order with no preferences", () => {
    const { pinned, rest } = arrange(PAGES, EMPTY_PREFS);

    expect(ids(pinned)).toEqual([]);
    expect(ids(rest)).toEqual(["/a", "/b", "/c", "/d"]);
  });

  it("follows the saved order and puts pinned pages first", () => {
    const { pinned, rest } = arrange(PAGES, prefs({ order: ["/d", "/c", "/b", "/a"], pinned: ["/b", "/c"] }));

    expect(ids(pinned)).toEqual(["/c", "/b"]);
    expect(ids(rest)).toEqual(["/d", "/a"]);
  });

  it("puts pages it does not know after the known ones, in default order", () => {
    const { rest } = arrange(PAGES, prefs({ order: ["/c", "/a"] }));

    expect(ids(rest)).toEqual(["/c", "/a", "/b", "/d"]);
  });

  it("ignores ids of pages that are not there", () => {
    const { pinned, rest } = arrange(PAGES, prefs({ order: ["/gone", "/b"], pinned: ["/gone"] }));

    expect(ids(pinned)).toEqual([]);
    expect(ids(rest)).toEqual(["/b", "/a", "/c", "/d"]);
  });

  it("never pins a hidden page", () => {
    const { pinned } = arrange(PAGES, prefs({ pinned: ["/a"], hidden: ["/a"] }));

    expect(ids(pinned)).toEqual([]);
  });
});

describe("railPages", () => {
  it("leaves out hidden pages", () => {
    const { pinned, rest } = railPages(PAGES, prefs({ pinned: ["/b"], hidden: ["/c"] }));

    expect(ids(pinned)).toEqual(["/b"]);
    expect(ids(rest)).toEqual(["/a", "/d"]);
  });
});

describe("dropPage", () => {
  it("moves a page down to after its target", () => {
    expect(dropPage(PAGES, EMPTY_PREFS, "/a", "/c").order).toEqual(["/b", "/c", "/a", "/d"]);
  });

  it("moves a page up to before its target", () => {
    expect(dropPage(PAGES, EMPTY_PREFS, "/d", "/b").order).toEqual(["/a", "/d", "/b", "/c"]);
  });

  it("does nothing when dropped on itself or on an unknown page", () => {
    expect(dropPage(PAGES, EMPTY_PREFS, "/a", "/a")).toBe(EMPTY_PREFS);
    expect(dropPage(PAGES, EMPTY_PREFS, "/a", "/zzz")).toBe(EMPTY_PREFS);
  });

  it("pins a page dropped among the pinned ones, and shows it", () => {
    const start = prefs({ pinned: ["/a"], hidden: ["/d"] });

    const next = dropPage(PAGES, start, "/d", "/a");

    expect(next.pinned).toEqual(["/d", "/a"]);
    expect(next.hidden).toEqual([]);
  });

  it("unpins a page dropped among the others", () => {
    const next = dropPage(PAGES, prefs({ pinned: ["/a", "/b"] }), "/a", "/c");

    expect(next.pinned).toEqual(["/b"]);
    expect(next.order).toEqual(["/b", "/c", "/a", "/d"]);
  });
});

describe("setPinned", () => {
  it("pins last among the pinned and shows the page", () => {
    const next = setPinned(PAGES, prefs({ pinned: ["/c"], hidden: ["/a"] }), "/a", true);

    expect(next.pinned).toEqual(["/c", "/a"]);
    expect(next.hidden).toEqual([]);
  });

  it("unpins to the top of the others", () => {
    const next = setPinned(PAGES, prefs({ pinned: ["/c", "/d"] }), "/c", false);

    expect(next.pinned).toEqual(["/d"]);
    expect(next.order).toEqual(["/d", "/c", "/a", "/b"]);
  });

  it("ignores an unknown page", () => {
    const start = prefs({ pinned: ["/c"] });

    expect(setPinned(PAGES, start, "/zzz", true)).toBe(start);
  });
});

describe("setHidden", () => {
  it("hides and unpins a pinned page", () => {
    const next = setHidden(PAGES, prefs({ pinned: ["/b"] }), "/b", true);

    expect(next.hidden).toEqual(["/b"]);
    expect(next.pinned).toEqual([]);
    expect(next.order[0]).toBe("/b");
  });

  it("shows a hidden page again where it stands", () => {
    const start = prefs({ order: ["/a", "/b", "/c", "/d"], hidden: ["/b"] });

    const next = setHidden(PAGES, start, "/b", false);

    expect(next.hidden).toEqual([]);
    expect(next.order).toEqual(["/a", "/b", "/c", "/d"]);
  });
});

describe("isDefault", () => {
  it("is true only for the empty arrangement", () => {
    expect(isDefault(EMPTY_PREFS)).toBe(true);
    expect(isDefault(prefs({ hidden: ["/a"] }))).toBe(false);
  });
});
