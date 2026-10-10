import { describe, expect, it } from "vitest";
import { commandsByTool } from "./toolCommands";

const LIST = [{ capability: "notes", name: "add", description: "", tool_name: "notes_add" }];

describe("commandsByTool", () => {
  it("maps built-in commands by tool name", () => {
    expect(commandsByTool(LIST, ["notes_add"], null).get("notes_add")).toBe("/notes add");
  });
  it("derives extension commands from the namespaced tool name", () => {
    const map = commandsByTool([], ["ext__run", "ext__", "other__x"], "ext");
    expect(map.get("ext__run")).toBe("/ext run");
    expect(map.has("ext__")).toBe(false);
    expect(map.has("other__x")).toBe(false);
  });
  it("derives nothing without an extension id", () => {
    expect(commandsByTool([], ["ext__run"], null).size).toBe(0);
  });
});
