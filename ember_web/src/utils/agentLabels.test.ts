import { describe, expect, it } from "vitest";
import { agentLabelFor } from "./agentLabels";

describe("agentLabelFor", () => {
  it("uses the known label, else the id, else nothing", () => {
    expect(agentLabelFor("main", { main: "Ember" })).toBe("Ember");
    expect(agentLabelFor("old-agent", { main: "Ember" })).toBe("old-agent");
    expect(agentLabelFor(undefined, { main: "Ember" })).toBeUndefined();
  });
});
