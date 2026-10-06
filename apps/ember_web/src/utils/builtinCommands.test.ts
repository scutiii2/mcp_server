import { describe, expect, it } from "vitest";
import { builtinCommand } from "./builtinCommands";

describe("builtinCommand", () => {
  it.each(["clear", "compact", "export", "share"])("knows /%s", (name) => {
    expect(builtinCommand(`/${name}`)).toBe(name);
  });

  it("ignores case and the spaces a picked suggestion leaves", () => {
    expect(builtinCommand("  /Clear ")).toBe("clear");
    expect(builtinCommand("/EXPORT ")).toBe("export");
  });

  it("is null for anything else, so other slash commands run as before", () => {
    expect(builtinCommand("/clear now")).toBeNull();
    expect(builtinCommand("/clearance")).toBeNull();
    expect(builtinCommand("/files list")).toBeNull();
    expect(builtinCommand("clear")).toBeNull();
    expect(builtinCommand("")).toBeNull();
  });
});
