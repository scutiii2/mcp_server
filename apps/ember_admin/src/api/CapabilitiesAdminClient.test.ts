import { afterEach, describe, expect, it, vi } from "vitest";
import { capabilitiesAdminClient } from "./CapabilitiesAdminClient";

afterEach(() => vi.restoreAllMocks());

function stubFetch(status: number, body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("capabilitiesAdminClient", () => {
  it("lists capabilities", async () => {
    stubFetch(200, [{ name: "vault", enabled: true }]);
    expect(await capabilitiesAdminClient.list()).toEqual([{ name: "vault", enabled: true }]);
  });

  it("switches one capability with PATCH", async () => {
    const fetchMock = stubFetch(200, { name: "vault", enabled: true });
    await capabilitiesAdminClient.setOnline("vault", true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/capabilities/vault");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ enabled: true });
  });

  it("refreshes with POST", async () => {
    const fetchMock = stubFetch(200, []);
    await capabilitiesAdminClient.refresh();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/capabilities/refresh");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
  });

  it("surfaces the server's message when going online fails", async () => {
    stubFetch(400, { detail: "boom" });
    await expect(capabilitiesAdminClient.setOnline("vault", true)).rejects.toThrow("boom");
  });
});
