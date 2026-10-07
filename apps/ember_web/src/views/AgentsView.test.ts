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

/** The page opens on the map; `asCards` flips it to the card grid. */
async function mountView(asCards = true) {
  const wrapper = mount(AgentsView);
  await flushPromises();
  if (asCards) await chip(wrapper, "Cards").trigger("click");
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

  it("shows the same rows in the map's details panel", async () => {
    const wrapper = await mountView(false);

    expect(wrapper.find(".details .llm").text()).toContain("claude-sonnet-5-5");
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

  describe("map view", () => {
    const node = (wrapper: Wrapper, id: string) => wrapper.findAll(".node").find((n) => n.find(".agent-id").text() === id)!;

    it("opens on the map with a node per agent and no cards", async () => {
      const wrapper = await mountView(false);

      expect(wrapper.findAll(".node")).toHaveLength(4);
      expect(cards(wrapper)).toHaveLength(0);
      expect(chip(wrapper, "Cards").exists()).toBe(true);
    });

    it("switches between the map and the cards", async () => {
      const wrapper = await mountView(false);

      await chip(wrapper, "Cards").trigger("click");
      expect(wrapper.findAll(".node")).toHaveLength(0);
      expect(cards(wrapper)).toHaveLength(4);

      await chip(wrapper, "Map").trigger("click");
      expect(wrapper.findAll(".node")).toHaveLength(4);
    });

    it("selects the entry agent first and links it to the next layer", async () => {
      const wrapper = await mountView(false);

      expect(node(wrapper, "ember").classes()).toContain("picked");
      const details = wrapper.find(".details");
      expect(details.find("h3").text()).toBe("EMBER");
      expect(details.text()).toContain("New chats");
      expect(details.text()).toContain("REVIEWER, PDF, OLD");
    });

    it("shows the details of the clicked node", async () => {
      const wrapper = await mountView(false);

      await node(wrapper, "pdf").trigger("click");

      expect(node(wrapper, "pdf").classes()).toContain("picked");
      expect(node(wrapper, "ember").classes()).not.toContain("picked");
      const details = wrapper.find(".details");
      expect(details.find("h3").text()).toBe("PDF");
      expect(details.text()).toContain("pdf does things.");
      expect(details.text()).toContain("Offline");
      expect(details.text()).toContain("EMBER");
    });

    it("falls back to the entry agent when the selected one disappears", async () => {
      const wrapper = await mountView(false);
      await node(wrapper, "pdf").trigger("click");

      list.mockResolvedValue([AGENTS[0], AGENTS[1]]);
      await chip(wrapper, "Refresh").trigger("click");
      await flushPromises();

      expect(wrapper.find(".details h3").text()).toBe("EMBER");
    });
  });
});
