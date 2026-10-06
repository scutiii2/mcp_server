import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";
import { useCountdown } from "./useCountdown";

describe("useCountdown", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function make(onZero = vi.fn()) {
    const scope = effectScope();
    const countdown = scope.run(() => useCountdown(onZero))!;
    return { countdown, onZero, scope };
  }

  it("counts down each second and calls onZero once at zero", () => {
    const { countdown, onZero } = make();
    countdown.start(3);
    expect(countdown.remaining.value).toBe(3);
    vi.advanceTimersByTime(2000);
    expect(countdown.remaining.value).toBe(1);
    expect(onZero).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(onZero).toHaveBeenCalledTimes(1);
    expect(countdown.running.value).toBe(false);
  });

  it("restarting replaces the running countdown", () => {
    const { countdown, onZero } = make();
    countdown.start(5);
    vi.advanceTimersByTime(2000);
    countdown.start(2);
    vi.advanceTimersByTime(2000);
    expect(onZero).toHaveBeenCalledTimes(1);
  });

  it("stop cancels it", () => {
    const { countdown, onZero } = make();
    countdown.start(2);
    countdown.stop();
    vi.advanceTimersByTime(5000);
    expect(onZero).not.toHaveBeenCalled();
  });

  it("stops when its scope is disposed", () => {
    const { countdown, onZero, scope } = make();
    countdown.start(2);
    scope.stop();
    vi.advanceTimersByTime(5000);
    expect(onZero).not.toHaveBeenCalled();
  });

  it("does not tick while the tab is hidden and re-syncs when it returns", () => {
    const { countdown, onZero } = make();
    countdown.start(10);
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    vi.advanceTimersByTime(4000);
    expect(countdown.remaining.value).toBe(10);
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    document.dispatchEvent(new Event("visibilitychange"));
    vi.advanceTimersByTime(1000);
    expect(countdown.remaining.value).toBe(9);
    expect(onZero).not.toHaveBeenCalled();
  });
});
