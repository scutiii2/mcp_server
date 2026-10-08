import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CopyButton from "./CopyButton.vue";

function setClipboard(writeText: () => Promise<void>): void {
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("CopyButton", () => {
  it("copies its text and says so for a moment", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard(writeText);
    const wrapper = mount(CopyButton, { props: { text: "the answer", label: "Copy answer" } });
    expect(wrapper.attributes("aria-label")).toBe("Copy answer");

    await wrapper.trigger("click");
    await vi.advanceTimersByTimeAsync(0);

    expect(writeText).toHaveBeenCalledWith("the answer");
    expect(wrapper.text()).toBe("Copied");

    await vi.advanceTimersByTimeAsync(1500);
    expect(wrapper.text()).toBe("");
    expect(wrapper.find("svg").exists()).toBe(true);
  });

  it("reports a failed copy", async () => {
    setClipboard(vi.fn().mockRejectedValue(new Error("denied")));
    Object.defineProperty(document, "execCommand", { value: () => false, configurable: true, writable: true });
    const wrapper = mount(CopyButton, { props: { text: "x" } });

    await wrapper.trigger("click");
    await vi.advanceTimersByTimeAsync(0);

    expect(wrapper.text()).toBe("Copy failed");
    expect(wrapper.classes()).toContain("failed");
  });

  it("copies the current text, not the text it was mounted with", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard(writeText);
    const wrapper = mount(CopyButton, { props: { text: "old" } });

    await wrapper.setProps({ text: "new" });
    await wrapper.trigger("click");

    expect(writeText).toHaveBeenCalledWith("new");
  });
});
