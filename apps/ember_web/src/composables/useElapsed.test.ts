import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, ref, type Ref } from "vue";
import { useElapsed } from "./useElapsed";

const T0 = Date.parse("2026-10-01T10:00:00Z");

/** Mounts a component that uses the composable, and hands back what it returns. */
function mountElapsed(since: Ref<number | null>, tickMs?: number) {
  let elapsed!: Ref<number>;
  const wrapper = mount(
    defineComponent({
      setup() {
        elapsed = useElapsed(since, tickMs);
        return () => h("span", elapsed.value);
      },
    }),
  );
  return { wrapper, elapsed: () => elapsed.value };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useElapsed", () => {
  it("is 0 while there is nothing running", () => {
    const { elapsed } = mountElapsed(ref(null));

    expect(elapsed()).toBe(0);
  });

  it("does not start a timer while nothing is running", () => {
    mountElapsed(ref(null));

    expect(vi.getTimerCount()).toBe(0);
  });

  it("shows the time already passed at once", () => {
    const { elapsed } = mountElapsed(ref(T0 - 5000));

    expect(elapsed()).toBe(5000);
  });

  it("keeps counting", async () => {
    const { elapsed } = mountElapsed(ref(T0));

    await vi.advanceTimersByTimeAsync(1000);

    expect(elapsed()).toBe(1000);
  });

  it("ticks about five times a second by default", async () => {
    const { elapsed } = mountElapsed(ref(T0));

    await vi.advanceTimersByTimeAsync(199);
    expect(elapsed()).toBe(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(elapsed()).toBe(200);
  });

  it("takes another tick length", async () => {
    const { elapsed } = mountElapsed(ref(T0), 1000);

    await vi.advanceTimersByTimeAsync(999);
    expect(elapsed()).toBe(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(elapsed()).toBe(1000);
  });

  it("starts when the start time is set later", async () => {
    const since = ref<number | null>(null);
    const { elapsed } = mountElapsed(since);

    since.value = T0;
    await vi.advanceTimersByTimeAsync(600);

    expect(elapsed()).toBe(600);
  });

  it("goes back to 0 and stops when it ends", async () => {
    const since = ref<number | null>(T0);
    const { elapsed } = mountElapsed(since);
    await vi.advanceTimersByTimeAsync(1000);

    since.value = null;
    await vi.advanceTimersByTimeAsync(0);

    expect(elapsed()).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("restarts from a new start time without a second timer", async () => {
    const since = ref<number | null>(T0);
    const { elapsed } = mountElapsed(since);
    await vi.advanceTimersByTimeAsync(2000);

    since.value = Date.now();
    await vi.advanceTimersByTimeAsync(400);

    expect(elapsed()).toBe(400);
    expect(vi.getTimerCount()).toBe(1);
  });

  it("never goes below 0 when the clock is behind the start time", () => {
    const { elapsed } = mountElapsed(ref(T0 + 60_000));

    expect(elapsed()).toBe(0);
  });

  it("stops its timer when the component goes away", () => {
    const { wrapper } = mountElapsed(ref(T0));
    expect(vi.getTimerCount()).toBe(1);

    wrapper.unmount();

    expect(vi.getTimerCount()).toBe(0);
  });
});
