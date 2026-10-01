import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usageClient, type MyUsage, type UsageWindow } from "../api/UsageClient";
import UsageGauges from "./UsageGauges.vue";

vi.mock("../api/UsageClient", () => ({ usageClient: { mine: vi.fn() } }));

const mine = vi.mocked(usageClient.mine);

const window = (used: number, limit: number, reset_at: string | null = null): UsageWindow => ({ used, limit, reset_at });

function usage(six: UsageWindow, week: UsageWindow): MyUsage {
  return { six_hour: six, weekly: week, report: {} as MyUsage["report"] };
}

async function mountGauges(busy = false) {
  const wrapper = mount(UsageGauges, { props: { busy } });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  vi.clearAllMocks();
  mine.mockResolvedValue(usage(window(25_000, 100_000), window(900_000, 1_000_000)));
});

describe("what it shows", () => {
  it("reads the account's usage for one day and shows both windows", async () => {
    const wrapper = await mountGauges();

    expect(mine).toHaveBeenCalledExactlyOnceWith(1);
    const gauges = wrapper.findAll(".gauge");
    expect(gauges.map((g) => g.find(".head").text())).toEqual(["6 h25k / 100k", "Week900k / 1M"]);
  });

  it("fills each bar to its share of the limit", async () => {
    const wrapper = await mountGauges();

    const bars = wrapper.findAll('[role="progressbar"]');
    expect(bars.map((b) => b.attributes("aria-valuenow"))).toEqual(["25", "90"]);
    expect(bars.map((b) => b.find("span").attributes("style"))).toEqual(["width: 25%;", "width: 90%;"]);
  });

  it("turns a bar red from 90%", async () => {
    mine.mockResolvedValue(usage(window(89, 100), window(90, 100)));
    const wrapper = await mountGauges();

    const fills = wrapper.findAll(".bar span");
    expect(fills.map((f) => f.classes().includes("full"))).toEqual([false, true]);
  });

  it("names the window and the exact numbers on hover, and when old tokens stop counting", async () => {
    mine.mockResolvedValue(usage(window(1234, 5000, "2026-10-01T12:30:00"), window(0, 9000, "2026-10-05T00:00:00")));
    const wrapper = await mountGauges();

    const [six, week] = wrapper.findAll(".gauge");
    expect(six!.attributes("title")).toContain("Last 6 hours: 1,234 of 5,000 tokens.");
    expect(six!.attributes("title")).toContain("Oldest tokens stop counting at");
    // Nothing used: nothing to expire.
    expect(week!.attributes("title")).toBe("Last 7 days: 0 of 9,000 tokens.");
  });

  it("shows only the windows that have a limit", async () => {
    mine.mockResolvedValue(usage(window(500, 0), window(500, 1000)));
    const wrapper = await mountGauges();

    expect(wrapper.findAll(".gauge").map((g) => g.find(".head span").text())).toEqual(["Week"]);
  });

  it("is not shown at all when nothing is limited", async () => {
    mine.mockResolvedValue(usage(window(500, 0), window(500, 0)));
    const wrapper = await mountGauges();

    expect(wrapper.find(".gauges").exists()).toBe(false);
  });

  it("is not shown before the first read arrives", () => {
    mine.mockReturnValue(new Promise(() => {}));
    const wrapper = mount(UsageGauges, { props: { busy: false } });

    expect(wrapper.find(".gauges").exists()).toBe(false);
  });
});

describe("when it reads again", () => {
  it("after an answer ends", async () => {
    const wrapper = await mountGauges(true);
    mine.mockClear();
    mine.mockResolvedValue(usage(window(40_000, 100_000), window(900_000, 1_000_000)));

    await wrapper.setProps({ busy: false });
    await flushPromises();

    expect(mine).toHaveBeenCalledOnce();
    expect(wrapper.find(".gauge .head").text()).toBe("6 h40k / 100k");
  });

  it("not when an answer starts", async () => {
    const wrapper = await mountGauges(false);
    mine.mockClear();

    await wrapper.setProps({ busy: true });
    await flushPromises();

    expect(mine).not.toHaveBeenCalled();
  });

  it("only the last read counts when answers end in quick succession", async () => {
    const wrapper = await mountGauges(true);
    let firstDone!: (u: MyUsage) => void;
    mine.mockReset();
    mine.mockReturnValueOnce(new Promise<MyUsage>((resolve) => (firstDone = resolve)));
    mine.mockResolvedValueOnce(usage(window(70_000, 100_000), window(900_000, 1_000_000)));

    await wrapper.setProps({ busy: false });
    await wrapper.setProps({ busy: true });
    await wrapper.setProps({ busy: false });
    await flushPromises();
    firstDone(usage(window(10_000, 100_000), window(900_000, 1_000_000))); // the older read, arriving late
    await flushPromises();

    expect(wrapper.find(".gauge .head").text()).toBe("6 h70k / 100k");
  });
});

describe("when the read fails", () => {
  it("shows nothing and does not throw", async () => {
    mine.mockRejectedValue(new Error("down"));

    const wrapper = await mountGauges();

    expect(wrapper.find(".gauges").exists()).toBe(false);
  });

  it("keeps the numbers it had", async () => {
    const wrapper = await mountGauges(true);
    mine.mockRejectedValue(new Error("down"));

    await wrapper.setProps({ busy: false });
    await flushPromises();

    expect(wrapper.find(".gauge .head").text()).toBe("6 h25k / 100k");
  });
});
