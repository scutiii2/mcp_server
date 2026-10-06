import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ElapsedTime from "./ElapsedTime.vue";

const T0 = Date.parse("2026-10-01T10:00:00Z");

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ElapsedTime", () => {
  it("shows the time since the start, to a tenth of a second", () => {
    const wrapper = mount(ElapsedTime, { props: { since: T0 - 2400 } });

    expect(wrapper.text()).toBe("2.4 s");
  });

  it("counts up while shown", async () => {
    const wrapper = mount(ElapsedTime, { props: { since: T0 } });

    await vi.advanceTimersByTimeAsync(3000);

    expect(wrapper.text()).toBe("3.0 s");
  });

  it("goes to minutes and padded seconds after a minute", async () => {
    const wrapper = mount(ElapsedTime, { props: { since: T0 - 63_000 } });

    expect(wrapper.text()).toBe("1 min 03 s");
  });

  it("follows a new start time", async () => {
    const wrapper = mount(ElapsedTime, { props: { since: T0 - 10_000 } });

    await wrapper.setProps({ since: T0 });

    expect(wrapper.text()).toBe("0.0 s");
  });

  it("stops its timer when removed", () => {
    const wrapper = mount(ElapsedTime, { props: { since: T0 } });

    wrapper.unmount();

    expect(vi.getTimerCount()).toBe(0);
  });
});
