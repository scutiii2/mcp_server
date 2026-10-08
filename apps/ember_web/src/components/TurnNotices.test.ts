import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import TurnNotices from "./TurnNotices.vue";

const NOTICES = [
  { id: "mynotes", label: "My notes", error: "Timed out" },
  { id: "wiki", label: "Wiki", error: "Its headers can't be read" },
];

describe("TurnNotices", () => {
  it("renders nothing when there are none", () => {
    expect(mount(TurnNotices, { props: { notices: [] } }).find(".notices").exists()).toBe(false);
  });

  it("says which extension was not used and why", () => {
    const w = mount(TurnNotices, { props: { notices: NOTICES } });

    const lines = w.findAll("li").map((li) => li.text());
    expect(lines).toEqual([
      "My notes wasn't used in this answer: Timed out",
      "Wiki wasn't used in this answer: Its headers can't be read",
    ]);
  });

  it("emits dismiss", async () => {
    const w = mount(TurnNotices, { props: { notices: NOTICES } });

    await w.get("button").trigger("click");

    expect(w.emitted("dismiss")).toHaveLength(1);
  });
});
