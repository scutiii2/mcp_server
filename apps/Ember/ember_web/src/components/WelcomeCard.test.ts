import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { CommandInfo } from "../api/CommandsClient";
import { GREETINGS } from "../utils/welcome";
import WelcomeCard from "./WelcomeCard.vue";

const command = (capability: string): CommandInfo => ({ capability, name: "list", description: "", tool_name: `${capability}_list` });

describe("WelcomeCard", () => {
  it("greets with one of the greetings", () => {
    const wrapper = mount(WelcomeCard, { props: { commands: [] } });

    expect(GREETINGS).toContain(wrapper.find("h2").text());
  });

  it("keeps its greeting while the commands change", async () => {
    const wrapper = mount(WelcomeCard, { props: { commands: [] } });
    const greeting = wrapper.find("h2").text();

    await wrapper.setProps({ commands: [command("files")] });

    expect(wrapper.find("h2").text()).toBe(greeting);
  });

  it("offers slash commands and lists what can be done when there are commands", () => {
    const wrapper = mount(WelcomeCard, { props: { commands: [command("files"), command("notes")] } });

    expect(wrapper.find(".tip").text()).toContain("Type / to run a command");
    expect(wrapper.find(".caps").text()).toBe("I can help you with: Files (/files), Notes (/notes)");
  });

  it("leaves slash commands out, and shows no list, when there are none", () => {
    const wrapper = mount(WelcomeCard, { props: { commands: [] } });

    expect(wrapper.find(".tip").text()).toBe("Type # for a saved prompt, or just ask a question.");
    expect(wrapper.find(".caps").exists()).toBe(false);
  });

  it("follows the commands when they arrive after the card is shown", async () => {
    const wrapper = mount(WelcomeCard, { props: { commands: [] } });

    await wrapper.setProps({ commands: [command("files")] });

    expect(wrapper.find(".tip").text()).toContain("Type / to run a command");
    expect(wrapper.find(".caps").exists()).toBe(true);
  });
});
