import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { ToolRunResult } from "../api/types";
import GuiResult from "./GuiResult.vue";

const result = (structured: Record<string, unknown>, isError = false, text = ""): ToolRunResult => ({ text, isError, structured });

describe("GuiResult", () => {
  it("secret: shows the value, hidden-toggle and copy", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const w = mount(GuiResult, { props: { spec: { kind: "secret", field: "password", detail: "message" }, result: result({ password: "s3cret!", message: "Generated." }) } });
    expect(w.get("[data-test=secret]").text()).toBe("s3cret!");
    expect(w.text()).toContain("Generated.");
    await w.get("[data-test=copy]").trigger("click");
    expect(writeText).toHaveBeenCalledWith("s3cret!");
    await w.get("[data-test=toggle]").trigger("click");
    expect(w.get("[data-test=secret]").text()).not.toContain("s3cret!");
    await w.get("[data-test=toggle]").trigger("click");
    expect(w.get("[data-test=secret]").text()).toBe("s3cret!");
  });

  it("message: plain text of the field, default 'message'", () => {
    const w = mount(GuiResult, { props: { spec: { kind: "message" }, result: result({ message: "All done." }) } });
    expect(w.text()).toContain("All done.");
  });

  it("table: a list of uniform objects becomes rows", () => {
    const rows = [{ name: "a", status: "up" }, { name: "b", status: "down" }];
    const w = mount(GuiResult, { props: { spec: { kind: "table", field: "apps" }, result: result({ apps: rows }) } });
    expect(w.findAll("th").map((h) => h.text())).toEqual(["name", "status"]);
    expect(w.findAll("tbody tr")).toHaveLength(2);
    expect(w.text()).toContain("down");
  });

  it("fields: label/value list of scalar fields", () => {
    const w = mount(GuiResult, { props: { spec: { kind: "fields" }, result: result({ length: 12, message: "ok" }) } });
    expect(w.text()).toContain("length");
    expect(w.text()).toContain("12");
  });

  it("a tool error shows its text, not the field", () => {
    const w = mount(GuiResult, { props: { spec: { kind: "secret", field: "password" }, result: result({}, true, "length must be between 8 and 128.") } });
    expect(w.text()).toContain("length must be between 8 and 128.");
    expect(w.find("[data-test=secret]").exists()).toBe(false);
  });

  it("a missing field says so instead of showing an empty box", () => {
    const w = mount(GuiResult, { props: { spec: { kind: "secret", field: "password" }, result: result({ other: 1 }) } });
    expect(w.text()).toMatch(/no value/i);
  });
});
