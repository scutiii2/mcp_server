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

  it("secret: shows a strength bar and label from the named bits field", () => {
    const w = mount(GuiResult, { props: { spec: { kind: "secret", field: "password", strength: "entropy_bits" }, result: result({ password: "x", entropy_bits: 131.2 }) } });
    expect(w.get("[data-test=strength]").text()).toBe("Excellent");
    expect(w.get("[data-test=bits]").text()).toContain("131");
    expect(w.get(".fill").classes()).toContain("excellent");
    expect((w.get(".fill").element as HTMLElement).style.width).toBe("100%");
  });

  it("secret: no strength bar without the option, or when the field is missing", () => {
    const plain = mount(GuiResult, { props: { spec: { kind: "secret", field: "password" }, result: result({ password: "x", entropy_bits: 50 }) } });
    expect(plain.find("[data-test=strength]").exists()).toBe(false);
    const missing = mount(GuiResult, { props: { spec: { kind: "secret", field: "password", strength: "entropy_bits" }, result: result({ password: "x" }) } });
    expect(missing.find("[data-test=strength]").exists()).toBe(false);
  });

  it("secret: groups the display but copies the whole value", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const w = mount(GuiResult, { props: { spec: { kind: "secret", field: "code", group: 3 }, result: result({ code: "123456" }) } });
    expect(w.get("[data-test=secret]").text()).toBe("123 456");
    await w.get("[data-test=copy]").trigger("click");
    expect(writeText).toHaveBeenCalledWith("123456");
  });

  it("secret: colours digits and symbols of a mixed value only", () => {
    const mixed = mount(GuiResult, { props: { spec: { kind: "secret", field: "p" }, result: result({ p: "ab12!" }) } });
    expect(mixed.findAll(".digit").map((e) => e.text())).toEqual(["12"]);
    expect(mixed.findAll(".symbol").map((e) => e.text())).toEqual(["!"]);
    const pin = mount(GuiResult, { props: { spec: { kind: "secret", field: "p" }, result: result({ p: "123456" }) } });
    expect(pin.find(".digit").exists()).toBe(false);
  });

  it("secret: hides as dots, not as the value", async () => {
    const w = mount(GuiResult, { props: { spec: { kind: "secret", field: "p", group: 3 }, result: result({ p: "123456" }) } });
    await w.get("[data-test=toggle]").trigger("click");
    expect(w.get("[data-test=secret]").text()).toBe("••••••");
  });

  it("secret: Generate again appears only when asked for, and says so", async () => {
    const without = mount(GuiResult, { props: { spec: { kind: "secret", field: "p" }, result: result({ p: "x" }) } });
    expect(without.find("[data-test=again]").exists()).toBe(false);
    const w = mount(GuiResult, { props: { spec: { kind: "secret", field: "p" }, result: result({ p: "x" }), canRegenerate: true } });
    await w.get("[data-test=again]").trigger("click");
    expect(w.emitted("again")).toHaveLength(1);
  });
});
