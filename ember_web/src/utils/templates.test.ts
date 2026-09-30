import { describe, expect, it } from "vitest";
import type { PromptTemplate } from "../api/TemplatesClient";
import { appendToDraft, filterTemplates, preview, templateQuery } from "./templates";

const tpl = (id: number, name: string, body = "text"): PromptTemplate => ({
  id,
  name,
  body,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
});

const LIST = [tpl(1, "Summarize"), tpl(2, "Code review"), tpl(3, "Review notes"), tpl(4, "Translate")];

describe("filterTemplates", () => {
  it("keeps everything for an empty or blank query", () => {
    expect(filterTemplates(LIST, "")).toBe(LIST);
    expect(filterTemplates(LIST, "   ")).toBe(LIST);
  });

  it("matches names anywhere, ignoring case, names that start with the query first", () => {
    expect(filterTemplates(LIST, "review").map((t) => t.id)).toEqual([3, 2]);
    expect(filterTemplates(LIST, "REV").map((t) => t.id)).toEqual([3, 2]);
  });

  it("keeps the given order inside each group", () => {
    const list = [tpl(1, "b review"), tpl(2, "a review"), tpl(3, "review b"), tpl(4, "review a")];

    expect(filterTemplates(list, "review").map((t) => t.id)).toEqual([3, 4, 1, 2]);
  });

  it("looks at the name, not the body", () => {
    expect(filterTemplates([tpl(1, "Alpha", "mentions beta")], "beta")).toEqual([]);
  });

  it("finds nothing when nothing matches", () => {
    expect(filterTemplates(LIST, "zzz")).toEqual([]);
  });
});

describe("templateQuery", () => {
  it.each([
    ["#", ""],
    ["#rev", "rev"],
    ["#code re", "code re"],
    ["#  spaced", "  spaced"],
  ])("%j -> %j", (draft, expected) => {
    expect(templateQuery(draft)).toBe(expected);
  });

  it.each([["hello"], [" #late"], [""], ["#one\ntwo"], ["/cmd"]])("%j is not a lookup", (draft) => {
    expect(templateQuery(draft)).toBeNull();
  });
});

describe("appendToDraft", () => {
  it("is the text alone when the draft is empty or blank", () => {
    expect(appendToDraft("", "body")).toBe("body");
    expect(appendToDraft("  \n ", "body")).toBe("body");
  });

  it("goes on a new line after what is typed, without stacking blank lines", () => {
    expect(appendToDraft("intro", "body")).toBe("intro\nbody");
    expect(appendToDraft("intro\n\n", "body")).toBe("intro\nbody");
  });
});

describe("preview", () => {
  it("is the first non-empty line, collapsed", () => {
    expect(preview("\n\n  first   line \nsecond")).toBe("first line");
  });

  it("cuts a long line with an ellipsis", () => {
    expect(preview("x".repeat(100), 10)).toBe(`${"x".repeat(9)}…`);
    expect(preview("x".repeat(10), 10)).toBe("x".repeat(10));
  });

  it("is empty for a blank body", () => {
    expect(preview("  \n ")).toBe("");
  });
});
