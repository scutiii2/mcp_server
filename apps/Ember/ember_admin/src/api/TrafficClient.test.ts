import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "./http";
import { trafficClient } from "./TrafficClient";

vi.mock("./http", () => ({ apiRequest: vi.fn() }));

const request = vi.mocked(apiRequest);

beforeEach(() => {
  vi.clearAllMocks();
  request.mockResolvedValue({} as never);
});

describe("trafficClient", () => {
  it("asks for the traffic report of a range", async () => {
    await trafficClient.analytics("30d");

    expect(request).toHaveBeenCalledExactlyOnceWith("GET", "/api/traffic/analytics?range=30d");
  });
});
