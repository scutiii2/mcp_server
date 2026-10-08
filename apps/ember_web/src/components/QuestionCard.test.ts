import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { PendingQuestion } from "../api/types";
import QuestionCard from "./QuestionCard.vue";

const PENDING: PendingQuestion = {
  id: "q1",
  questions: [
    {
      header: "Format",
      question: "Which format?",
      multi_select: false,
      options: [{ label: "CSV", description: "Plain text" }, { label: "JSON" }],
    },
    { header: "Extras", question: "Which extras?", multi_select: true, options: [{ label: "Totals" }, { label: "Chart" }] },
  ],
};

function mountCard(props: Record<string, unknown> = {}) {
  return mount(QuestionCard, { props: { pending: PENDING, answering: false, ...props } });
}

const option = (w: ReturnType<typeof mountCard>, q: number, label: string) =>
  w.findAll(".q")[q]!.findAll("button.opt").find((b) => b.find(".label").text() === label)!;
const submit = (w: ReturnType<typeof mountCard>) => w.get("button.submit");
const skip = (w: ReturnType<typeof mountCard>) => w.get("button.skip");

describe("QuestionCard", () => {
  it("shows every question with its header, options and an Other choice", () => {
    const w = mountCard();

    expect(w.findAll(".q")).toHaveLength(2);
    const first = w.findAll(".q")[0]!;
    expect(first.text()).toContain("Format");
    expect(first.text()).toContain("Which format?");
    expect(first.text()).toContain("Plain text");
    expect(first.findAll("button.opt").map((b) => b.find(".label").text())).toEqual(["CSV", "JSON", "Other"]);
  });

  it("starts with Submit off and Skip on", () => {
    const w = mountCard();

    expect((submit(w).element as HTMLButtonElement).disabled).toBe(true);
    expect((skip(w).element as HTMLButtonElement).disabled).toBe(false);
  });

  it("a single-select question keeps one choice at a time", async () => {
    const w = mountCard();

    await option(w, 0, "CSV").trigger("click");
    await option(w, 0, "JSON").trigger("click");

    expect(option(w, 0, "CSV").attributes("aria-pressed")).toBe("false");
    expect(option(w, 0, "JSON").attributes("aria-pressed")).toBe("true");
  });

  it("a multi-select question toggles choices on and off", async () => {
    const w = mountCard();

    await option(w, 1, "Totals").trigger("click");
    await option(w, 1, "Chart").trigger("click");
    await option(w, 1, "Totals").trigger("click");

    expect(option(w, 1, "Totals").attributes("aria-pressed")).toBe("false");
    expect(option(w, 1, "Chart").attributes("aria-pressed")).toBe("true");
  });

  it("Submit needs every question answered and then sends the answers in order", async () => {
    const w = mountCard();
    await option(w, 0, "CSV").trigger("click");
    expect((submit(w).element as HTMLButtonElement).disabled).toBe(true);
    await option(w, 1, "Totals").trigger("click");
    await option(w, 1, "Chart").trigger("click");
    expect((submit(w).element as HTMLButtonElement).disabled).toBe(false);

    await w.get("form").trigger("submit");

    expect(w.emitted("answer")).toEqual([
      ["q1", [{ selected: ["CSV"], other: null }, { selected: ["Totals", "Chart"], other: null }]],
    ]);
  });

  it("Other reveals a text box; typed text alone counts as an answer", async () => {
    const w = mountCard();
    expect(w.findAll("input[type=text]")).toHaveLength(0);

    await option(w, 0, "Other").trigger("click");
    await w.get(".q input[type=text]").setValue("  XML  ");
    await option(w, 1, "Chart").trigger("click");
    await w.get("form").trigger("submit");

    expect(w.emitted("answer")![0]).toEqual([
      "q1",
      [{ selected: [], other: "XML" }, { selected: ["Chart"], other: null }],
    ]);
  });

  it("Other with nothing typed is not an answer", async () => {
    const w = mountCard();
    await option(w, 0, "Other").trigger("click");
    await option(w, 1, "Chart").trigger("click");

    expect((submit(w).element as HTMLButtonElement).disabled).toBe(true);
  });

  it("choosing Other on a single-select question drops the listed choice", async () => {
    const w = mountCard();
    await option(w, 0, "CSV").trigger("click");

    await option(w, 0, "Other").trigger("click");

    expect(option(w, 0, "CSV").attributes("aria-pressed")).toBe("false");
    expect(option(w, 0, "Other").attributes("aria-pressed")).toBe("true");
  });

  it("Skip sends a skip, even with nothing chosen", async () => {
    const w = mountCard();

    await skip(w).trigger("click");

    expect(w.emitted("skip")).toEqual([["q1"]]);
  });

  it("turns every button off while the answer is on its way", () => {
    const w = mountCard({ answering: true });

    expect(w.findAll("button").every((b) => (b.element as HTMLButtonElement).disabled)).toBe(true);
  });

  it("shows the text of a question as text, never as markup", () => {
    const w = mountCard({
      pending: {
        id: "q1",
        questions: [
          { header: "x", question: "<img src=x onerror=alert(1)>", multi_select: false, options: [{ label: "<b>A</b>" }, { label: "B" }] },
        ],
      },
    });

    expect(w.find("img").exists()).toBe(false);
    expect(w.find("b").exists()).toBe(false);
    expect(w.text()).toContain("<img src=x onerror=alert(1)>");
  });
});
