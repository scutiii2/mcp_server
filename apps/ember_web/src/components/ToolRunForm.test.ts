import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { JsonSchema } from "../api/types";
import ToolRunForm from "./ToolRunForm.vue";

vi.mock("../api/CommandsClient", () => ({ commandsClient: { options: vi.fn(), upload: vi.fn() } }));

const SCHEMA: JsonSchema = {
  type: "object",
  properties: {
    length: { type: "integer", minimum: 8, maximum: 128, default: 20, input: "range" },
    use_upper: { type: "boolean", default: true },
  },
};

const mountForm = (props: Record<string, unknown> = {}) =>
  mount(ToolRunForm, { props: { schema: SCHEMA, running: false, ...props } });

describe("ToolRunForm live mode", () => {
  it("runs once on mount with the defaults", () => {
    const w = mountForm({ live: true });
    expect(w.emitted("run")).toEqual([[{ length: 20, use_upper: true }]]);
  });

  it("does not run on mount when not live", () => {
    expect(mountForm().emitted("run")).toBeUndefined();
  });

  it("runs when a control is committed, not while a slider is still moving", async () => {
    const w = mountForm({ live: true });
    const slider = w.get("input[type=range]");
    (slider.element as HTMLInputElement).value = "64";
    await slider.trigger("input"); // dragging fires only `input` (VTU's setValue would also fire `change`)
    expect(w.emitted("run")).toHaveLength(1);
    await slider.trigger("change"); // the release
    expect(w.emitted("run")).toHaveLength(2);
    expect(w.emitted("run")![1]).toEqual([{ length: 64, use_upper: true }]);
  });

  it("runs when a toggle chip changes", async () => {
    const w = mountForm({ live: true });
    await w.get("input[type=checkbox]").setValue(false);
    await w.get("input[type=checkbox]").trigger("change");
    expect(w.emitted("run")!.at(-1)).toEqual([{ length: 20, use_upper: false }]);
  });

  it("does not run for values that do not validate", async () => {
    const schema: JsonSchema = { type: "object", properties: { secret: { type: "string" } }, required: ["secret"] };
    const w = mountForm({ live: true, schema });
    expect(w.emitted("run")).toBeUndefined();
    (w.get("input").element as HTMLInputElement).value = "abc";
    await w.get("input").trigger("input");
    await w.get("input").trigger("change");
    expect(w.emitted("run")).toEqual([[{ secret: "abc" }]]);
  });

  it("hides the Run button and shows the slider's value", () => {
    const live = mountForm({ live: true });
    expect(live.find("button.run").exists()).toBe(false);
    expect(live.get("output").text()).toBe("20");
    expect(mountForm().find("button.run").exists()).toBe(true);
    expect(mountForm().find("output").exists()).toBe(false);
  });

  it("a normal form ignores change events", async () => {
    const w = mountForm();
    await w.get("input[type=range]").trigger("change");
    expect(w.emitted("run")).toBeUndefined();
  });
});
