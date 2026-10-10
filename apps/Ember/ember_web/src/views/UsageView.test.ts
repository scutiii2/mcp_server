import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usageClient, type MyUsage, type UsageRecordRow } from "../api/UsageClient";
import { useAuthStore } from "../stores/auth";
import { downloadText } from "../utils/chatExport";
import UsageView from "./UsageView.vue";

vi.mock("../api/UsageClient", () => ({ usageClient: { mine: vi.fn(), allAccounts: vi.fn(), records: vi.fn() } }));
vi.mock("../utils/chatExport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../utils/chatExport")>()),
  downloadText: vi.fn(),
}));

const mine = vi.mocked(usageClient.mine);
const allAccounts = vi.mocked(usageClient as typeof usageClient & { allAccounts: ReturnType<typeof vi.fn> }).allAccounts;
const records = vi.mocked(usageClient.records);
const download = vi.mocked(downloadText);

const hourly = (hour: number, tokens: number): number[] => {
  const list = new Array<number>(24).fill(0);
  list[hour] = tokens;
  return list;
};

function usage(extra: Partial<MyUsage["report"]> = {}): MyUsage {
  return {
    six_hour: { used: 10, limit: 100, reset_at: null },
    weekly: { used: 20, limit: 0, reset_at: null },
    report: {
      days: 30,
      since: "2026-09-15T00:00:00",
      total_tokens: 1500,
      input_tokens: 1000,
      output_tokens: 500,
      summary_tokens: 0,
      turns: 4,
      chats: 2,
      by_agent: [{ agent: "claude", model: "opus", tokens: 1500 }],
      daily: [{ date: "2026-10-01", tokens: 1500 }],
      hourly: hourly(14, 1500),
      group_by: "agent",
      groups: [],
      ...extra,
    },
  };
}

function account(permissions: string[]) {
  return { id: 1, username: "root", email: "root@example.com", email_verified: true, roles: [], permissions };
}

async function mountView(permissions = ["chat.use", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"]) {
  setActivePinia(createPinia());
  useAuthStore().account = account(permissions);
  const wrapper = mount(UsageView);
  await flushPromises();
  return wrapper;
}

const rangeButton = (wrapper: Awaited<ReturnType<typeof mountView>>, label: string) =>
  wrapper.findAll(".ranges button").find((b) => b.text() === label)!;

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-15T08:00:00Z"));
  vi.spyOn(Date.prototype, "getTimezoneOffset").mockReturnValue(0);
  mine.mockResolvedValue(usage());
  allAccounts.mockResolvedValue([]);
  records.mockResolvedValue([]);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("the period buttons", () => {
  it("offers This month first, then 7 days to 12 months, with 30 days chosen", async () => {
    const wrapper = await mountView();

    const buttons = wrapper.findAll(".ranges button").filter((b) => !b.classes().includes("export"));
    expect(buttons.map((b) => b.text())).toEqual(["This month", "7 days", "30 days", "90 days", "12 months"]);
    expect(buttons.map((b) => b.attributes("aria-pressed"))).toEqual(["false", "false", "true", "false", "false"]);
  });

  it("loads the last 30 days to begin with", async () => {
    await mountView();

    expect(mine).toHaveBeenCalledWith(30, undefined, { groupBy: "agent" });
  });

  it("This month asks from the 1st", async () => {
    const wrapper = await mountView();

    await rangeButton(wrapper, "This month").trigger("click");
    await flushPromises();

    expect(mine).toHaveBeenLastCalledWith(30, "2026-10-01", { groupBy: "agent" });
    expect(rangeButton(wrapper, "This month").attributes("aria-pressed")).toBe("true");
  });

  it.each([
    ["7 days", 7],
    ["90 days", 90],
    ["12 months", 365],
  ])("%s asks for %d days", async (label, days) => {
    const wrapper = await mountView();

    await rangeButton(wrapper, label).trigger("click");
    await flushPromises();

    expect(mine).toHaveBeenLastCalledWith(days, undefined, { groupBy: "agent" });
  });

  it("keeps an administrator's usage personal for every period", async () => {
    const wrapper = await mountView(["chat.use", "usage.all.view", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"]);
    expect(allAccounts).not.toHaveBeenCalled();
    expect(wrapper.text()).not.toContain("All accounts");

    await rangeButton(wrapper, "This month").trigger("click");
    await flushPromises();

    expect(allAccounts).not.toHaveBeenCalled();
  });

  it("does not ask for them without usage.all.view", async () => {
    await mountView(["chat.use", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"]);

    expect(allAccounts).not.toHaveBeenCalled();
  });
});

describe("the new figures", () => {
  it("shows the busiest hour and the favorite agent", async () => {
    const wrapper = await mountView();

    const insights = wrapper.findAll(".insight").map((s) => s.text());
    expect(insights).toContain("Busiest hour (your time) 2 PM");
    expect(insights).toContain("Favorite agent claude opus");
  });

  it("moves the busiest hour into the viewer's time zone", async () => {
    vi.spyOn(Date.prototype, "getTimezoneOffset").mockReturnValue(-120); // UTC+2

    const wrapper = await mountView();

    expect(wrapper.findAll(".insight").map((s) => s.text())).toContain("Busiest hour (your time) 4 PM");
  });

  it("leaves both out when nothing was used in the period", async () => {
    mine.mockResolvedValue(usage({ hourly: new Array<number>(24).fill(0), by_agent: [], daily: [], total_tokens: 0 }));

    const wrapper = await mountView();

    expect(wrapper.find(".insights").exists()).toBe(false);
  });
});

describe("the 12-month heatmap", () => {
  it("is drawn from its own request for the last 366 days, once", async () => {
    const wrapper = await mountView();

    expect(mine).toHaveBeenCalledWith(366);
    expect(wrapper.find(".heatmap").exists()).toBe(true);
    expect(wrapper.text()).toContain("Last 12 months");
    expect(wrapper.text()).toContain("Days are UTC days.");

    await rangeButton(wrapper, "7 days").trigger("click");
    await flushPromises();

    expect(mine.mock.calls.filter((call) => call[0] === 366)).toHaveLength(1);
  });

  it("does not follow the chosen period", async () => {
    mine.mockImplementation(async (days) =>
      days === 366 ? usage({ daily: [{ date: "2026-03-03", tokens: 9 }] }) : usage({ daily: [{ date: "2026-10-01", tokens: 1500 }] }),
    );

    const wrapper = await mountView();
    await rangeButton(wrapper, "7 days").trigger("click");
    await flushPromises();

    const titles = wrapper.findAll(".heatmap .cell").map((c) => c.attributes("aria-label") ?? "");
    expect(titles.some((t) => t.startsWith("2026-03-03"))).toBe(true);
  });

  it("says so when nothing was used in the last year", async () => {
    mine.mockImplementation(async (days) => (days === 366 ? usage({ daily: [] }) : usage()));

    const wrapper = await mountView();

    expect(wrapper.find(".heatmap").exists()).toBe(false);
    expect(wrapper.text()).toContain("No usage in the last 12 months.");
  });

  it("is left out, and the rest of the page still works, when its request fails", async () => {
    mine.mockImplementation(async (days) => {
      if (days === 366) throw new Error("boom");
      return usage();
    });

    const wrapper = await mountView();

    expect(wrapper.text()).not.toContain("Last 12 months");
    expect(wrapper.find(".heatmap").exists()).toBe(false);
    expect(wrapper.find(".stats").exists()).toBe(true);
    expect(wrapper.find(".error").exists()).toBe(false);
  });
});

const groupButton = (wrapper: Awaited<ReturnType<typeof mountView>>, label: string) =>
  wrapper.findAll(".breakdown button").find((b) => b.text() === label)!;

function row(extra: Partial<UsageRecordRow> = {}): UsageRecordRow {
  return {
    id: 1,
    turn_id: "t",
    kind: "chat",
    chat_id: "c",
    agent: "calc",
    agent_id: "calc",
    provider_id: "openai",
    gateway: "azure",
    model: "gpt-x",
    input_tokens: 20,
    output_tokens: 5,
    total_tokens: 25,
    started_at: "2026-10-04T09:12:04",
    finished_at: "2026-10-04T09:12:05",
    delegated_by: "main",
    created_at: "2026-10-04T09:12:06",
    ...extra,
  };
}

describe("group by", () => {
  it("groups the report by the chosen field", async () => {
    mine.mockResolvedValue(
      usage({ group_by: "agent", groups: [{ key: "calc", tokens: 30, input_tokens: 20, output_tokens: 10, turns: 1 }] }),
    );
    const wrapper = await mountView();

    await groupButton(wrapper, "Provider").trigger("click");
    await flushPromises();

    expect(mine).toHaveBeenLastCalledWith(30, undefined, expect.objectContaining({ groupBy: "provider" }));
  });

  it("lists the groups under a heading for the field", async () => {
    mine.mockResolvedValue(
      usage({ group_by: "agent", groups: [{ key: "calc", tokens: 30, input_tokens: 20, output_tokens: 10, turns: 1 }] }),
    );
    const wrapper = await mountView();

    expect(wrapper.find("table.groups th").text()).toBe("Agent");
    expect(wrapper.find("table.groups tbody tr").text()).toContain("calc");
    mine.mockResolvedValue(
      usage({ group_by: "gateway", groups: [{ key: "azure", tokens: 30, input_tokens: 20, output_tokens: 10, turns: 1 }] }),
    );
    await groupButton(wrapper, "Gateway").trigger("click");
    await flushPromises();
    expect(wrapper.find("table.groups th").text()).toBe("Gateway");
  });

  it("says None when there are no groups", async () => {
    const wrapper = await mountView();

    expect(wrapper.find("table.groups").exists()).toBe(false);
    expect(wrapper.find(".breakdown > p.muted").text()).toBe("None.");
  });

  it("keeps the heading of the loaded report while the next grouping loads", async () => {
    const group = { key: "calc", tokens: 30, input_tokens: 20, output_tokens: 10, turns: 1 };
    mine.mockResolvedValue(usage({ group_by: "agent", groups: [group] }));
    const wrapper = await mountView();
    mine.mockReturnValue(new Promise(() => {})); // the provider report is still loading

    await groupButton(wrapper, "Provider").trigger("click");

    expect(wrapper.find("table.groups th").text()).toBe("Agent");
  });

  it("applies only the latest request when responses arrive out of order", async () => {
    const later = (data: MyUsage) => data;
    let releaseFirst: (value: MyUsage) => void = () => {};
    mine.mockImplementation((days) => {
      if (days === 366) return Promise.resolve(usage());
      return new Promise((resolve) => {
        if (calls++ === 0) releaseFirst = resolve;
        else resolve(later(usage({ total_tokens: 777 })));
      });
    });
    let calls = 0;
    setActivePinia(createPinia());
    useAuthStore().account = account(["chat.use", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"]);
    const wrapper = mount(UsageView); // first request (30 days) stays pending
    await flushPromises();
    await rangeButton(wrapper, "7 days").trigger("click"); // second request answers at once
    await flushPromises();

    releaseFirst(usage({ total_tokens: 111 })); // the stale one answers last
    await flushPromises();

    expect(wrapper.text()).toContain("777");
    expect(wrapper.text()).not.toContain("111");
  });
});

describe("the recent calls list", () => {
  it("asks for the latest 100 rows of the period", async () => {
    await mountView();

    expect(records).toHaveBeenLastCalledWith(30, undefined, { limit: 100 });
  });

  it("lists each row with its provider, gateway and time", async () => {
    records.mockResolvedValue([row()]);
    const wrapper = await mountView();

    const text = wrapper.find(".calls .call").text();
    expect(text).toContain("calc");
    expect(text).toContain("← main");
    expect(text).toContain("openai");
    expect(text).toContain("azure");
    expect(text).toContain("gpt-x");
    expect(text).toContain("25");
    expect(text).toContain(new Date("2026-10-04T09:12:04Z").toLocaleString());
  });

  it("leaves out what an older row lacks", async () => {
    records.mockResolvedValue([
      row({ agent_id: null, agent: null, provider_id: null, gateway: null, model: null, input_tokens: null, output_tokens: null, delegated_by: null, started_at: null }),
    ]);
    const wrapper = await mountView();

    const item = wrapper.find(".calls .call");
    expect(item.text()).toContain(new Date("2026-10-04T09:12:06Z").toLocaleString());
    expect(item.find(".call-agent").text()).toBe("unknown");
    expect(item.find(".chip").exists()).toBe(false);
    expect(item.find(".call-tokens").text()).toBe("25");
  });

  it("is left out, and the report still shows, when its request fails", async () => {
    records.mockRejectedValue(new Error("boom"));

    const wrapper = await mountView();

    expect(wrapper.find(".error").exists()).toBe(false);
    expect(wrapper.find(".stats").exists()).toBe(true);
    expect(wrapper.find(".calls").exists()).toBe(false);
    expect(wrapper.text()).toContain("Could not load recent calls.");
    expect(wrapper.text()).not.toMatch(/Recent calls\s*None\./);
  });
});

describe("Export .md", () => {
  const exportButton = (wrapper: Awaited<ReturnType<typeof mountView>>) => wrapper.find(".ranges .export");

  it("is off until the report has loaded", async () => {
    mine.mockReturnValue(new Promise(() => {}));
    setActivePinia(createPinia());
    useAuthStore().account = account(["chat.use", "tools.execute", "files.upload", "files.download", "chat.share", "extensions.personal.manage"]);

    const wrapper = mount(UsageView);

    expect(exportButton(wrapper).attributes("disabled")).toBeDefined();
  });

  it("downloads the period as a Markdown file named for it", async () => {
    const wrapper = await mountView();

    await exportButton(wrapper).trigger("click");

    expect(download).toHaveBeenCalledOnce();
    const [name, text, type] = download.mock.calls[0]!;
    expect(name).toBe("usage-30d-2026-10-15.md");
    expect(type).toBe("text/markdown");
    expect(text).toContain("# Token usage - root");
    expect(text).toContain("Range: 30 days (since 2026-09-15).");
    expect(text).toContain("| Total tokens | 1,500 |");
  });

  it("labels the file and the range for This month", async () => {
    const wrapper = await mountView();
    await rangeButton(wrapper, "This month").trigger("click");
    await flushPromises();

    await exportButton(wrapper).trigger("click");

    const [name, text] = download.mock.calls[0]!;
    expect(name).toBe("usage-month-2026-10-15.md");
    expect(text).toContain("Range: This month");
  });

  it("exports what is on the page, not the 12-month request", async () => {
    mine.mockImplementation(async (days) => (days === 366 ? usage({ total_tokens: 999_999 }) : usage({ total_tokens: 1500 })));
    const wrapper = await mountView();

    await exportButton(wrapper).trigger("click");

    expect(download.mock.calls[0]![1]).toContain("| Total tokens | 1,500 |");
  });

  it("does nothing when the report failed to load", async () => {
    mine.mockRejectedValue(new Error("down"));

    const wrapper = await mountView();

    expect(wrapper.find(".error").text()).toContain("down");
    expect(exportButton(wrapper).attributes("disabled")).toBeDefined();
  });
});

describe("activity line chart", () => {
  it("keeps inactive days at zero between real daily values", async () => {
    mine.mockResolvedValue(usage({ since: "2026-10-13T00:00:00", daily: [
      { date: "2026-10-13", tokens: 10 }, { date: "2026-10-15", tokens: 30 },
    ] }));
    const wrapper = await mountView();
    expect(wrapper.find(".activity polyline").exists()).toBe(true);
    expect(wrapper.find(".activity polygon").attributes("fill")).toBe("var(--accent)");
    await wrapper.find(".activity .chart .chip").trigger("click");
    expect(wrapper.findAll(".activity .chart tbody tr td").map((cell) => cell.text())).toEqual(["10", "0", "30"]);
  });
});


it("does not fetch workspace usage without chat access", async () => {
  const wrapper = await mountView(["usage.all.view"]);
  expect(allAccounts).not.toHaveBeenCalled();
  expect(mine).not.toHaveBeenCalled();
  expect(wrapper.text()).not.toContain("All accounts");
});
