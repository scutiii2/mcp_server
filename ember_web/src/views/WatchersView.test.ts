import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import { watchersClient, type WatcherInfo, type WatchersReport } from "../api/WatchersClient";
import WatchersView from "./WatchersView.vue";

vi.mock("../api/WatchersClient", () => ({ watchersClient: { list: vi.fn() } }));

const list = vi.mocked(watchersClient.list);

const NOW = Date.parse("2026-10-05T12:00:00Z");
const HOUR = 3_600_000;
const ago = (hours: number) => new Date(NOW - hours * HOUR).toISOString();

const run = (capability: string, key: string, phase: string, started: number, ended?: number): WatcherInfo => ({
  capability,
  key,
  phase,
  started_at: ago(started),
  last_polled_at: ended === undefined ? undefined : ago(ended),
});

const WATCHERS: WatcherInfo[] = [
  run("email", "invoice-1", "failed", 12, 11),
  run("email", "welcome-2", "completed", 6, 5),
  run("ssh", "probe-3", "running", 2),
  run("backup", "nightly-4", "completed", 30, 29), // before the 24 hour window
];

const report = (watchers = WATCHERS, errors: string[] = []): WatchersReport => ({ watchers, errors });

async function mountView(query = "") {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/watchers", component: { render: () => null } }] });
  await router.push(`/watchers${query}`);
  await router.isReady();
  const wrapper = mount(WatchersView, { global: { plugins: [router] } });
  await flushPromises();
  return { wrapper, router };
}

const button = (wrapper: Awaited<ReturnType<typeof mountView>>["wrapper"], label: string) =>
  wrapper.findAll("button").find((b) => b.text() === label)!;
const lanes = (wrapper: Awaited<ReturnType<typeof mountView>>["wrapper"]) =>
  wrapper.findAll(".timeline .row:not(.axis):not(.child) .label").map((l) => l.text());
const tile = (wrapper: Awaited<ReturnType<typeof mountView>>["wrapper"], name: string) =>
  wrapper.findAll(".tile").find((t) => t.find(".label").text() === name)!;

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
  vi.setSystemTime(NOW);
  list.mockResolvedValue(report());
});

afterEach(() => {
  vi.useRealTimers();
});

describe("WatchersView", () => {
  it("shows the last 24 hours: one lane per capability that has runs in it, failing one first", async () => {
    const { wrapper } = await mountView();

    expect(list).toHaveBeenCalledTimes(1);
    expect(lanes(wrapper)).toEqual(["email", "ssh"]);
    expect(wrapper.find(".live").text()).toBe("Live · updated just now");
  });

  it("counts the runs in the tiles", async () => {
    const { wrapper } = await mountView();

    expect(tile(wrapper, "Running").find(".value").text()).toBe("1");
    expect(tile(wrapper, "Running").find(".sub").text()).toBe("oldest 2h 0m 0s");
    expect(tile(wrapper, "Succeeded").find(".value").text()).toBe("1");
    expect(tile(wrapper, "Succeeded").find(".sub").text()).toBe("the last 24 hours");
    expect(tile(wrapper, "Failed").find(".value").text()).toBe("1");
    expect(tile(wrapper, "Failed").find(".sub").text()).toBe("1 capability affected");
  });

  it("starts with the failing capability open and the others closed, then leaves it to the reader", async () => {
    const { wrapper } = await mountView();

    expect(wrapper.findAll(".timeline .child .label").map((l) => l.text())).toEqual(["invoice-1", "welcome-2"]);
    expect(wrapper.findAll(".list .row")).toHaveLength(2);

    await wrapper.findAll(".timeline .cap")[1]!.trigger("click"); // open ssh
    await wrapper.findAll(".timeline .cap")[0]!.trigger("click"); // close email
    expect(wrapper.findAll(".timeline .child .label").map((l) => l.text())).toEqual(["probe-3"]);
    expect(wrapper.findAll(".list .row")).toHaveLength(1);
  });

  it("widens to everything for 7d and All", async () => {
    const { wrapper } = await mountView();

    await button(wrapper, "7d").trigger("click");
    expect(lanes(wrapper)).toEqual(["email", "ssh", "backup"]);

    await button(wrapper, "24h").trigger("click");
    await button(wrapper, "All").trigger("click");
    expect(lanes(wrapper)).toEqual(["email", "ssh", "backup"]);
    expect(tile(wrapper, "Succeeded").find(".sub").text()).toBe("all time");
  });

  it("searches capability and key", async () => {
    const { wrapper } = await mountView();

    await wrapper.find(".search").setValue("probe");

    expect(lanes(wrapper)).toEqual(["ssh"]);
    await wrapper.find(".search").setValue("nothing like this");
    expect(wrapper.text()).toContain("No watchers match the filters.");
  });

  it("narrows to one capability from the address, with all its lanes open", async () => {
    const { wrapper } = await mountView("?capability=ssh");

    expect(lanes(wrapper)).toEqual(["ssh"]);
    expect(wrapper.findAll(".timeline .child")).toHaveLength(1);
    expect(tile(wrapper, "Failed").find(".value").text()).toBe("0");
    expect(wrapper.find(".trigger").text()).toContain("ssh");
  });

  it("writes the focus to the address and clears it", async () => {
    const { wrapper, router } = await mountView();

    await wrapper.find(".trigger").trigger("click");
    await wrapper.findAll(".option").find((o) => o.text().startsWith("ssh"))!.trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query.capability).toBe("ssh");
    expect(lanes(wrapper)).toEqual(["ssh"]);

    await wrapper.find(".trigger").trigger("click");
    await wrapper.findAll(".option")[0]!.trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query.capability).toBeUndefined();
    expect(lanes(wrapper)).toEqual(["email", "ssh"]);
  });

  it("treats a capability that is not there as all", async () => {
    const { wrapper } = await mountView("?capability=gone");

    expect(lanes(wrapper)).toEqual(["email", "ssh"]);
    expect(wrapper.find(".trigger").text()).toContain("All capabilities");
  });

  it("refreshes every 15 seconds and on demand", async () => {
    const { wrapper } = await mountView();

    vi.advanceTimersByTime(15_000);
    await flushPromises();
    expect(list).toHaveBeenCalledTimes(2);

    await button(wrapper, "Refresh").trigger("click");
    await flushPromises();
    expect(list).toHaveBeenCalledTimes(3);
  });

  it("counts up how long ago it updated", async () => {
    const { wrapper } = await mountView();

    vi.advanceTimersByTime(8_000); // the clock ticks; the next refresh is at 15 s
    await flushPromises();

    expect(wrapper.find(".live").text()).toBe("Live · updated just now");
    vi.advanceTimersByTime(7_000);
    await flushPromises();
    expect(list).toHaveBeenCalledTimes(2);
  });

  it("keeps lanes where they were when a refresh changes the ranking", async () => {
    const { wrapper } = await mountView();
    expect(lanes(wrapper)).toEqual(["email", "ssh"]);

    // ssh starts failing and email is fine: ranked first now, but the lanes hold still.
    list.mockResolvedValue(report([run("email", "invoice-1", "completed", 12, 11), run("ssh", "probe-3", "failed", 2, 1)]));
    await button(wrapper, "Refresh").trigger("click");
    await flushPromises();

    expect(lanes(wrapper)).toEqual(["email", "ssh"]);
    expect(wrapper.findAll(".timeline .alert")).toHaveLength(1);
  });

  it("shows the top lanes and the rest on request", async () => {
    const many = Array.from({ length: 12 }, (_, i) => run(`cap${String(i).padStart(2, "0")}`, "k", "completed", 3, 2));
    list.mockResolvedValue(report(many));
    const { wrapper } = await mountView();

    expect(lanes(wrapper)).toEqual(many.slice(0, 8).map((w) => w.capability));
    expect(button(wrapper, "Show all 12 capabilities")).toBeDefined();

    await button(wrapper, "Show all 12 capabilities").trigger("click");
    expect(lanes(wrapper)).toHaveLength(12);

    await button(wrapper, "Show top 8").trigger("click");
    expect(lanes(wrapper)).toHaveLength(8);
  });

  it("never hides a capability that fails, even past the top lanes", async () => {
    const calm = Array.from({ length: 12 }, (_, i) => run(`cap${String(i).padStart(2, "0")}`, "k", "completed", 3, 2));
    list.mockResolvedValue(report(calm));
    const { wrapper } = await mountView();
    expect(lanes(wrapper)).toHaveLength(8);

    list.mockResolvedValue(report([...calm.slice(0, 11), run("cap11", "k", "failed", 3, 2)]));
    await button(wrapper, "Refresh").trigger("click");
    await flushPromises();

    expect(lanes(wrapper)).toEqual([...calm.slice(0, 8).map((w) => w.capability), "cap11"]);
    expect(wrapper.findAll(".timeline .alert")).toHaveLength(1);
  });

  it("says so when nothing is running", async () => {
    list.mockResolvedValue(report([]));
    const { wrapper } = await mountView();

    expect(wrapper.text()).toContain("No watchers are running.");
    expect(wrapper.find(".trigger").exists()).toBe(false);
  });

  it("shows the error and keeps the last data when a refresh fails", async () => {
    const { wrapper } = await mountView();
    list.mockRejectedValue(new Error("mcp_server is down"));

    await button(wrapper, "Refresh").trigger("click");
    await flushPromises();

    expect(wrapper.find(".error").text()).toContain("mcp_server is down");
    expect(lanes(wrapper)).toEqual(["email", "ssh"]);
    expect(wrapper.find(".live").text()).toContain("Not updating");
  });

  it("names the capabilities that did not answer", async () => {
    list.mockResolvedValue(report(WATCHERS, ["calendar: timed out"]));
    const { wrapper } = await mountView();

    expect(wrapper.find(".error").text()).toContain("calendar: timed out");
  });

  it("stops its timers when the page goes away", async () => {
    const { wrapper } = await mountView();

    wrapper.unmount();
    vi.advanceTimersByTime(60_000);

    expect(list).toHaveBeenCalledTimes(1);
  });
});
