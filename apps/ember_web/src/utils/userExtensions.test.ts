import { describe, expect, it } from "vitest";
import type { UserExtension } from "../api/UserExtensionsClient";
import { matchesUserExtension, userExtensionSummary } from "./userExtensions";

const base: UserExtension = {
  id: "notes",
  label: "My notes",
  description: "",
  url: "https://notes.example.com/mcp",
  header_names: [],
  enabled: true,
  status: "connected",
  error: null,
  tools: ["search", "add"],
};

describe("userExtensionSummary", () => {
  it("counts the tools of a connected extension", () => {
    expect(userExtensionSummary(base)).toBe("2 tools");
    expect(userExtensionSummary({ ...base, tools: ["search"] })).toBe("1 tool");
    expect(userExtensionSummary({ ...base, tools: [] })).toBe("0 tools");
  });

  it("says why it brings nothing", () => {
    expect(userExtensionSummary({ ...base, enabled: false })).toBe("Not enabled");
    expect(userExtensionSummary({ ...base, status: "error", error: "Timed out" })).toBe("Not connected");
    expect(userExtensionSummary({ ...base, status: "unknown", error: "Couldn't check right now" })).toBe("Not checked yet");
  });
});

describe("matchesUserExtension", () => {
  it("matches everything for a blank query", () => {
    expect(matchesUserExtension(base, "")).toBe(true);
    expect(matchesUserExtension(base, "   ")).toBe(true);
  });

  it("matches the label, the id and the tool names, ignoring case", () => {
    expect(matchesUserExtension(base, "NOTES")).toBe(true);
    expect(matchesUserExtension(base, "notes")).toBe(true);
    expect(matchesUserExtension(base, "sear")).toBe(true);
    expect(matchesUserExtension(base, "zzz")).toBe(false);
  });
});
