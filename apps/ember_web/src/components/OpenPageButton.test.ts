import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import OpenPageButton from "./OpenPageButton.vue";

const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:rest(.*)", component: {} }] });

describe("OpenPageButton", () => {
  it("opens an external page in a new tab, without leaking the opener", () => {
    const w = mount(OpenPageButton, { props: { to: "http://127.0.0.1:5174/", external: true } });

    expect(w.text()).toBe("Open page");
    expect(w.attributes("href")).toBe("http://127.0.0.1:5174/");
    expect(w.attributes("target")).toBe("_blank");
    expect(w.attributes("rel")).toBe("noopener noreferrer");
  });

  it("links an in-app route in the same tab", () => {
    const w = mount(OpenPageButton, { props: { to: "/capabilities/pdf" }, global: { plugins: [router] } });

    expect(w.text()).toBe("Open page");
    expect(w.attributes("href")).toBe("/capabilities/pdf");
    expect(w.attributes("target")).toBeUndefined();
  });

  it("shows a custom label", () => {
    const w = mount(OpenPageButton, { props: { to: "http://127.0.0.1:5174/", external: true, label: "Open app" } });

    expect(w.text()).toBe("Open app");
  });

  it("hides its arrow from screen readers", () => {
    const w = mount(OpenPageButton, { props: { to: "/x" }, global: { plugins: [router] } });

    expect(w.find("svg").attributes("aria-hidden")).toBe("true");
  });
});
