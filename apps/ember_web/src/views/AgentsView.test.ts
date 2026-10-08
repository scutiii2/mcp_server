import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { agentsClient, type AgentListing } from "../api/AgentsClient";
import AgentsView from "./AgentsView.vue";

vi.mock("../api/AgentsClient", () => ({ agentsClient: { list: vi.fn() } }));

const list = vi.mocked(agentsClient.list);

const agent = (id: string, extra: Partial<AgentListing> = {}): AgentListing => ({
  id,
  label: id.toUpperCase(),
  entry: false,
  orchestrator: false,
  focus: `${id} does things.`,
  status: "running",
  provider: null,
  gateway: null,
  model: null,
  tiers: [],
  ...extra,
});

const AGENTS = [
  agent("ember", { entry: true, orchestrator: true, provider: "anthropic", gateway: "openrouter", model: "claude-sonnet-5-5" }),
  agent("reviewer"),
  agent("pdf", { status: "offline" }),
  agent("old", { status: "disabled", focus: "" }),
];

type Wrapper = ReturnType<typeof mount>;

const chip = (wrapper: Wrapper, text: string) => wrapper.findAll("button.chip").find((b) => b.text() === text)!;

async function mountView() {
  const wrapper = mount(AgentsView);
  await flushPromises();
  return wrapper;
}

const cards = (wrapper: Wrapper) => wrapper.findAll(".agent-card");

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  list.mockResolvedValue(AGENTS);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("AgentsView", () => {
  it("shows a card per agent with its name, id, focus and a status word", async () => {
    const wrapper = await mountView();

    const found = cards(wrapper);
    expect(found).toHaveLength(4);
    expect(wrapper.findAll("button.chip").map((button) => button.text())).toEqual(["Refresh"]);
    expect(found[1].find("h3").text()).toBe("REVIEWER");
    expect(found[1].find(".agent-id").text()).toBe("reviewer");
    expect(found[1].find(".focus").text()).toBe("reviewer does things.");
    expect(found.map((c) => c.find(".status").text())).toEqual(["● Running", "● Running", "○ Offline", "– Disabled"]);
  });

  it("marks the entry agent and the orchestrator, and nobody else", async () => {
    const wrapper = await mountView();

    const found = cards(wrapper);
    expect(found[0].classes()).toContain("entry");
    expect(found[0].findAll(".tag").map((t) => t.text())).toEqual(["Entry", "Orchestrator"]);
    expect(found[1].classes()).not.toContain("entry");
    expect(found[1].find(".tags").exists()).toBe(false);
  });

  it("says so when an agent has no description", async () => {
    const wrapper = await mountView();

    expect(cards(wrapper)[3].find(".focus").text()).toBe("No description.");
  });

  it("shows provider, gateway and model, and hides the ones an agent does not set", async () => {
    list.mockResolvedValue([
      AGENTS[0],
      agent("partial", { provider: "openai" }),
      agent("bare"),
    ]);
    const wrapper = await mountView();

    const found = cards(wrapper);
    expect(found[0].findAll("dt").map((t) => t.text())).toEqual(["Provider", "Gateway", "Model"]);
    expect(found[0].findAll("dd").map((t) => t.text())).toEqual(["anthropic", "openrouter", "claude-sonnet-5-5"]);
    expect(found[1].findAll("dt").map((t) => t.text())).toEqual(["Provider"]);
    expect(found[2].find(".llm").exists()).toBe(false);
  });

  it("lists each tier with its model, keeps what the tier is for in a title, and hides an empty list", async () => {
    list.mockResolvedValue([
      agent("ember", {
        tiers: [
          { tier: "light", id: "haiku", use_for: "quick lookups" },
          { tier: "heavy", id: "opus", use_for: "hard reasoning" },
        ],
      }),
      agent("bare"),
    ]);
    const wrapper = await mountView();

    const found = cards(wrapper);
    const items = found[0].findAll(".tiers li");
    expect(items.map((li) => li.findAll("span").map((span) => span.text()))).toEqual([
      ["light", "haiku"],
      ["heavy", "opus"],
    ]);
    expect(items[0].find(".tier-model").attributes("title")).toBe("quick lookups");
    expect(found[0].findAll("dt")).toHaveLength(0);
    expect(found[1].find(".tiers").exists()).toBe(false);
  });

  it("summarises the statuses and leaves out the empty ones", async () => {
    const wrapper = await mountView();
    expect(wrapper.find(".summary").text()).toBe("2 running · 1 offline · 1 disabled");

    list.mockResolvedValue([agent("ember", { entry: true })]);
    await chip(wrapper, "Refresh").trigger("click");
    await flushPromises();

    expect(wrapper.find(".summary").text()).toBe("1 running");
  });

  it("says when there are no agents", async () => {
    list.mockResolvedValue([]);

    const wrapper = await mountView();

    expect(wrapper.text()).toContain("No agents are running or defined.");
    expect(cards(wrapper)).toHaveLength(0);
  });

  it("shows the error and keeps the cards it already had when a refresh fails", async () => {
    const wrapper = await mountView();
    list.mockRejectedValue(new Error("boom"));

    await chip(wrapper, "Refresh").trigger("click");
    await flushPromises();

    expect(wrapper.find(".error").text()).toContain("boom");
    expect(cards(wrapper)).toHaveLength(4);
  });

  it("refreshes every 15 seconds and stops when the page closes", async () => {
    const wrapper = await mountView();
    expect(list).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(15_000);
    expect(list).toHaveBeenCalledTimes(2);

    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(list).toHaveBeenCalledTimes(2);
  });
});
