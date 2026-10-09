import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { agentsAdminClient, type AgentFile } from "../api/AgentsAdminClient";
import AgentsAdminView from "./AgentsAdminView.vue";

const EMBER: AgentFile = { id: "ember", label: "Ember", port: 9100, entry: true, orchestrator: true, llm: { provider: "anthropic", gateway: "openrouter" } };
const CALC: AgentFile = {
  id: "calc", label: "Calc", port: 9103, focus: "Maths", temperature: 0.2,
  llm: { provider: "anthropic", gateway: "claude", temperature: 0.1 },
} as AgentFile;
const PROVIDERS = {
  anthropic: [{ id: "claude", label: "Claude", model: "m", tiers: [{ tier: "light", id: "haiku" }, { tier: "standard", id: "sonnet" }, { tier: "heavy", id: "opus" }, { tier: "extreme", id: "fable" }] }, { id: "openrouter", label: "OpenRouter", model: "m", tiers: [] }],
  openai: [{ id: "gpt", label: "GPT", model: "m", tiers: [] }],
  laya: [{ id: "local", label: "Local", model: "m", tiers: [] }],
};

// jsdom has no <dialog> methods.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

beforeEach(() => {
  vi.spyOn(agentsAdminClient, "list").mockResolvedValue([EMBER, CALC]);
  vi.spyOn(agentsAdminClient, "gateways").mockResolvedValue(PROVIDERS);
  vi.spyOn(agentsAdminClient, "live").mockResolvedValue({
    ember: { status: "running", tiers: [{ tier: "light", id: "free-model", use_for: "lookups" }, { tier: "heavy", id: "big-model", use_for: "hard tasks" }] },
    calc: { status: "offline", tiers: [] },
  });
});
afterEach(() => vi.restoreAllMocks());

async function mounted() {
  const wrapper = mount(AgentsAdminView, { attachTo: document.body, global: { plugins: [createPinia()] } });
  await flushPromises();
  return wrapper;
}

describe("AgentsAdminView", () => {
  it("lists agents with model, port and live status", async () => {
    const wrapper = await mounted();
    expect(wrapper.findAll("[data-test=agent]")).toHaveLength(2);
    expect(wrapper.find("[data-id=ember]").text()).toContain("openrouter");
    expect(wrapper.find("[data-id=ember]").text()).toContain("9100");
    expect(wrapper.find("[data-id=ember] [aria-label='Model tiers']").text()).toContain("big-model");
    expect(wrapper.find("[data-id=calc] [data-test=status]").text()).toContain("Offline");
  });

  it("still lists agents when the live status is not available", async () => {
    vi.spyOn(agentsAdminClient, "live").mockRejectedValue(new Error("Forbidden"));
    const wrapper = await mounted();
    expect(wrapper.findAll("[data-test=agent]")).toHaveLength(2);
    expect(wrapper.find("[data-test=status]").exists()).toBe(false);
  });

  it("creates an agent from the form with the chosen provider and gateway", async () => {
    const create = vi.spyOn(agentsAdminClient, "create").mockResolvedValue({ id: "docs" });
    const wrapper = await mounted();

    await wrapper.find("[data-test=new]").trigger("click");
    await wrapper.find("[data-test=id]").setValue("docs");
    await wrapper.find("[data-test=label]").setValue("Docs");
    await wrapper.find("[data-test=provider]").setValue("openai");
    await wrapper.find("[data-test=gateway]").setValue("gpt");
    await wrapper.find("[data-test=url]").setValue("http://10.0.0.5:9104/mcp");
    await wrapper.find("[data-test=persona]").setValue("Be brief.");
    await wrapper.find("[data-test=allow]").setValue("docs_*, wiki_*");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(create).toHaveBeenCalledOnce();
    const [id, config] = create.mock.calls[0]!;
    expect(id).toBe("docs");
    expect(config).toMatchObject({
      label: "Docs", port: 9104, url: "http://10.0.0.5:9104/mcp", enabled: true, entry: false,
      llm: { provider: "openai", gateway: "gpt" },
      persona: "Be brief.", tools: { allow: ["docs_*", "wiki_*"], deny: [] },
    });
    expect(wrapper.find("[data-test=notice]").text()).toContain("Created docs");
  });

  it("clears a gateway the new provider does not offer", async () => {
    const wrapper = await mounted();
    await wrapper.find("[data-id=calc] [data-test=edit]").trigger("click");
    const gateway = wrapper.find<HTMLSelectElement>("[data-test=gateway]");
    expect(gateway.element.value).toBe("claude");
    await wrapper.find("[data-test=provider]").setValue("openai");
    expect(gateway.element.value).toBe("");
  });

  it("keeps fields the form does not show when saving an edit", async () => {
    const update = vi.spyOn(agentsAdminClient, "update").mockResolvedValue(CALC);
    const wrapper = await mounted();

    await wrapper.find("[data-id=calc] [data-test=edit]").trigger("click");
    expect(wrapper.find<HTMLInputElement>("[data-test=id]").element.disabled).toBe(true);
    await wrapper.find("[data-test=label]").setValue("Calculator");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const [id, config] = update.mock.calls[0]!;
    expect(id).toBe("calc");
    expect(config).toMatchObject({ label: "Calculator", port: 9103, temperature: 0.2, llm: { temperature: 0.1, gateway: "claude" } });
    expect(config).not.toHaveProperty("id");
  });

  it("shows the reason when ai_agent refuses a save and keeps the form open", async () => {
    vi.spyOn(agentsAdminClient, "create").mockRejectedValue(new Error("port 9104 is already used by enabled agent 'x'"));
    const wrapper = await mounted();
    await wrapper.find("[data-test=new]").trigger("click");
    await wrapper.find("[data-test=id]").setValue("docs");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(wrapper.find("[data-test=form-error]").text()).toContain("already used");
    expect(wrapper.find("dialog").attributes("open")).toBeDefined();
  });

  it("rejects a port that is not a number in range before calling the server", async () => {
    const create = vi.spyOn(agentsAdminClient, "create").mockResolvedValue({ id: "docs" });
    const wrapper = await mounted();
    await wrapper.find("[data-test=new]").trigger("click");
    await wrapper.find("[data-test=id]").setValue("docs");
    await wrapper.find("[data-test=port]").setValue("70000");
    await wrapper.find("form").trigger("submit");
    expect(create).not.toHaveBeenCalled();
    expect(wrapper.find("[data-test=form-error]").text()).toContain("Port");
  });

  it("removes an agent only after its id is confirmed, and never offers the entry agent", async () => {
    const remove = vi.spyOn(agentsAdminClient, "remove").mockResolvedValue(undefined);
    const wrapper = await mounted();

    expect(wrapper.find<HTMLButtonElement>("[data-id=ember] [data-test=remove]").element.disabled).toBe(true);
    await wrapper.find("[data-id=calc] [data-test=remove]").trigger("click");
    const confirm = wrapper.findAllComponents({ name: "ConfirmModal" }).find((c) => c.props("title") === "Remove agent")!;
    expect(confirm.props("requireText")).toBe("calc");
    expect(remove).not.toHaveBeenCalled();
    await confirm.vm.$emit("confirm");
    await flushPromises();

    expect(remove).toHaveBeenCalledWith("calc");
    expect(wrapper.find("[data-id=calc]").exists()).toBe(false);
  });

  it("previews which tiers an agent may use and saves the range", async () => {
    const update = vi.spyOn(agentsAdminClient, "update").mockResolvedValue(CALC);
    const wrapper = await mounted();
    await wrapper.find("[data-id=calc] [data-test=edit]").trigger("click");

    const allowed = () => wrapper.findAll("[data-test=tier-preview] li:not(.off)").map((li) => li.attributes("data-tier"));
    expect(allowed()).toEqual(["light", "standard", "heavy", "extreme"]);
    await wrapper.find("[data-test=min-tier]").setValue("standard");
    await wrapper.find("[data-test=max-tier]").setValue("standard");
    expect(allowed()).toEqual(["standard"]);
    expect(wrapper.find("[data-tier=standard]").text()).toContain("sonnet");

    await wrapper.find("form").trigger("submit");
    await flushPromises();
    expect(update.mock.calls[0]![1].llm).toMatchObject({ min_tier: "standard", max_tier: "standard" });
  });

  it("refuses a weakest tier that is stronger than the strongest", async () => {
    const update = vi.spyOn(agentsAdminClient, "update").mockResolvedValue(CALC);
    const wrapper = await mounted();
    await wrapper.find("[data-id=calc] [data-test=edit]").trigger("click");
    await wrapper.find("[data-test=min-tier]").setValue("heavy");
    await wrapper.find("[data-test=max-tier]").setValue("light");
    await wrapper.find("form").trigger("submit");
    expect(update).not.toHaveBeenCalled();
    expect(wrapper.find("[data-test=form-error]").text()).toContain("weakest");
  });

  it("saves the model settings, identity override and no routing for an orchestrator", async () => {
    const update = vi.spyOn(agentsAdminClient, "update").mockResolvedValue(EMBER);
    const wrapper = await mounted();
    await wrapper.find("[data-id=ember] [data-test=edit]").trigger("click");

    await wrapper.find("[data-test=identity]").setValue("You are Ember.");
    await wrapper.find("[data-test=temperature]").setValue("0.3");
    await wrapper.find("[data-test=max-tokens]").setValue("2048");
    await wrapper.find("[data-test=max-tool-rounds]").setValue("8");
    await wrapper.find("[data-test=max-effort]").setValue("medium");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const config = update.mock.calls[0]![1];
    expect(config).toMatchObject({
      identity: "You are Ember.",
      llm: { temperature: 0.3, max_tokens: 2048, max_tool_rounds: 8, max_effort: "medium" },
    });
    expect(config).not.toHaveProperty("routing");
  });

  it("refuses a model setting that is out of range before calling the server", async () => {
    const update = vi.spyOn(agentsAdminClient, "update").mockResolvedValue(CALC);
    const wrapper = await mounted();
    await wrapper.find("[data-id=calc] [data-test=edit]").trigger("click");
    await wrapper.find("[data-test=temperature]").setValue("5");
    await wrapper.find("form").trigger("submit");
    expect(update).not.toHaveBeenCalled();
    expect(wrapper.find("[data-test=form-error]").text()).toContain("Temperature");
  });

  it("previews the assembled prompt for the draft and shows a refusal", async () => {
    const preview = vi.spyOn(agentsAdminClient, "previewPrompt").mockResolvedValue("Your name is Ember: Calc.");
    const wrapper = await mounted();
    await wrapper.find("[data-id=calc] [data-test=edit]").trigger("click");
    await wrapper.find("[data-test=preview-caveman]").setValue(true);
    await wrapper.find("[data-test=preview]").trigger("click");
    await flushPromises();

    expect(preview).toHaveBeenCalledWith("calc", expect.objectContaining({ port: 9103 }), true);
    expect(wrapper.find("[data-test=preview-text]").text()).toBe("Your name is Ember: Calc.");

    preview.mockRejectedValue(new Error("llm.provider: must be one of"));
    await wrapper.find("[data-test=preview]").trigger("click");
    await flushPromises();
    expect(wrapper.find("[data-test=preview-error]").text()).toContain("llm.provider");
    expect(wrapper.find("[data-test=preview-text]").exists()).toBe(false);
  });

  it("opens the shared prompts dialog", async () => {
    vi.spyOn(agentsAdminClient, "prompts").mockResolvedValue({ values: {}, defaults: {}, overridden: [] });
    const wrapper = await mounted();
    await wrapper.find("[data-test=shared-prompts]").trigger("click");
    expect(wrapper.findComponent({ name: "SharedPromptsModal" }).props("open")).toBe(true);
  });
});
