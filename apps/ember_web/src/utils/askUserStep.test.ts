import { describe, expect, it } from "vitest";
import type { ToolStep } from "../api/types";
import { describeAskUser } from "./askUserStep";

const step = (overrides: Partial<ToolStep> = {}): ToolStep => ({
  tool: "ask_user",
  label: "",
  ok: true,
  arguments: {
    questions: [
      { header: "Format", question: "Which format?", multi_select: false, options: [{ label: "CSV" }, { label: "JSON" }] },
      { header: "Extras", question: "Which extras?", multi_select: true, options: [{ label: "Totals" }, { label: "Chart" }] },
    ],
  },
  result: "The user answered:\n- Which format?: CSV\n- Which extras?: Totals, Chart; other: a title",
  ...overrides,
});

describe("describeAskUser", () => {
  it("is null for any other tool", () => {
    expect(describeAskUser(step({ tool: "tool_srv_stopApp" }))).toBeNull();
  });

  it("pairs each question with what was answered", () => {
    expect(describeAskUser(step())).toEqual(["Format: CSV", "Extras: Totals, Chart; other: a title"]);
  });

  it("says when the user skipped or did not answer", () => {
    expect(
      describeAskUser(step({ result: "The user skipped these questions. Continue with your best judgement and say what you assumed." })),
    ).toEqual(["Format: skipped", "Extras: skipped"]);
    expect(describeAskUser(step({ result: "The user did not answer in time. Continue." }))).toEqual([
      "Format: no answer",
      "Extras: no answer",
    ]);
  });

  it("falls back to the headers alone when the answers cannot be read", () => {
    expect(describeAskUser(step({ result: "garbled", ok: false }))).toEqual(["Format", "Extras"]);
  });

  it("is null when the arguments are not questions", () => {
    expect(describeAskUser(step({ arguments: { nope: 1 } }))).toBeNull();
  });
});
