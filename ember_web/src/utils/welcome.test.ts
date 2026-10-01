import { describe, expect, it } from "vitest";
import type { CommandInfo } from "../api/CommandsClient";
import { GREETINGS, capabilityLine, pickGreeting, welcomeTip } from "./welcome";

const command = (capability: string, name = "list"): CommandInfo => ({
  capability,
  name,
  description: "",
  tool_name: `${capability}_${name}`,
});

describe("pickGreeting", () => {
  it("picks by the random number it is given", () => {
    expect(pickGreeting(() => 0)).toBe(GREETINGS[0]);
    expect(pickGreeting(() => 0.5)).toBe(GREETINGS[3]);
    expect(pickGreeting(() => 0.99)).toBe(GREETINGS[6]);
  });

  it("stays inside the list even for a random number of exactly 1", () => {
    expect(pickGreeting(() => 1)).toBe(GREETINGS[6]);
  });

  it("has seven greetings, all different", () => {
    expect(GREETINGS).toHaveLength(7);
    expect(new Set(GREETINGS).size).toBe(7);
  });

  it("uses Math.random when no source is given", () => {
    expect(GREETINGS).toContain(pickGreeting());
  });
});

describe("welcomeTip", () => {
  it("offers slash commands, saved prompts and a plain question when there are commands", () => {
    expect(welcomeTip(true)).toBe("Type / to run a command, # for a saved prompt, or just ask a question.");
  });

  it("leaves out slash commands when there are none", () => {
    expect(welcomeTip(false)).toBe("Type # for a saved prompt, or just ask a question.");
  });
});

describe("capabilityLine", () => {
  it("is empty without commands", () => {
    expect(capabilityLine([])).toBe("");
  });

  it("names each capability once with its slash id", () => {
    const line = capabilityLine([command("files", "list"), command("files", "read"), command("notes")]);

    expect(line).toBe("I can help you with: Files (/files), Notes (/notes)");
  });

  it("makes a readable label from an id with underscores or dashes", () => {
    expect(capabilityLine([command("watcher_status"), command("app-launcher")])).toBe(
      "I can help you with: Watcher status (/watcher_status), App launcher (/app-launcher)",
    );
  });

  it("keeps the order the commands came in", () => {
    expect(capabilityLine([command("zeta"), command("alpha")])).toBe("I can help you with: Zeta (/zeta), Alpha (/alpha)");
  });

  it("lists ten and says how many more", () => {
    const many = Array.from({ length: 13 }, (_, i) => command(`cap${i + 1}`));

    const line = capabilityLine(many);

    expect(line).toContain("Cap10 (/cap10)");
    expect(line).not.toContain("Cap11");
    expect(line.endsWith(", and 3 more")).toBe(true);
  });

  it("says nothing about more when exactly ten fit", () => {
    const ten = Array.from({ length: 10 }, (_, i) => command(`cap${i + 1}`));

    expect(capabilityLine(ten)).not.toContain("more");
  });
});
