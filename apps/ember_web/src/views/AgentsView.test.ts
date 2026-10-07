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
  ...extra,
});

const AGENTS = [
  agent("ember", { entry: true, orchestrator: true }),
  agent("reviewer"),
  agent("pdf", { status: "offline" }),
  agent("old", { status: "disabled", focus: "" }),
];

async function mountView() {
  const wrapper = mount(AgentsView);
  await flushPromises();
  return wrapper;
}

const cards = (wrapper: Awaited<ReturnType<typeof mountView>>) => wrapper.findAll(".agent-card");

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

  it("summarises the statuses and leaves out the empty ones", async () => {
    const wrapper = await mountView();
    expect(wrapper.find(".summary").text()).toBe("2 running · 1 offline · 1 disabled");

    list.mockResolvedValue([agent("ember", { entry: true })]);
    await wrapper.find("button.chip").trigger("click");
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

    await wrapper.find("button.chip").trigger("click");
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
