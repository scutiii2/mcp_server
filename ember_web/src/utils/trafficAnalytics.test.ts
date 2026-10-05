import { describe, expect, it } from "vitest";
import { LATENCY_PARTS, STATUS_CLASSES, STATUS_PARTS, formatDuration, latencyLabel } from "./trafficAnalytics";

describe("formatDuration", () => {
  it.each([
    [0, "0 ms"],
    [80, "80 ms"],
    [999.6, "1000 ms"],
    [1000, "1 s"],
    [1200, "1.2 s"],
    [5000, "5 s"],
    [12_345, "12.3 s"],
  ])("%s ms is %s", (ms, text) => {
    expect(formatDuration(ms)).toBe(text);
  });
});

describe("latencyLabel", () => {
  it("writes a value at the cap as 'at least', since the server only knows latency in bands", () => {
    expect(latencyLabel(5000, 5000)).toBe("5 s+");
    expect(latencyLabel(250, 5000)).toBe("250 ms");
  });

  it("writes a dash when nothing was measured", () => {
    expect(latencyLabel(null, 5000)).toBe("–");
  });
});

describe("chart parts", () => {
  it("has one part per status class, in stacking order, with its own colour token", () => {
    expect(STATUS_PARTS.map((p) => p.id)).toEqual([...STATUS_CLASSES]);
    expect(new Set(STATUS_PARTS.map((p) => p.color)).size).toBe(4);
    expect(STATUS_PARTS.every((p) => p.color.startsWith("var(--http-"))).toBe(true);
  });

  it("has a median and a slowest-5% line", () => {
    expect(LATENCY_PARTS.map((p) => p.id)).toEqual(["p50", "p95"]);
  });
});
