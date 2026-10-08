import { beforeEach, describe, expect, it, vi } from "vitest";

const runTool = vi.fn();

vi.mock("../api/McpServerClient", () => ({
  McpServerClient: class {
    listTools = async () => [{ name: "tool_files_export", title: "Export", description: "Export", inputSchema: {} }];
    runTool = runTool;
  },
}));

vi.mock("../api/CommandsClient", () => ({
  commandsClient: {
    list: async () => [{ capability: "files", name: "export", description: "Export", tool_name: "tool_files_export" }],
  },
}));

import { SlashCommandRunner } from "./slashCommands";

const MARKER = '[[DOWNLOAD filename="a.csv" bytes="5" url="/server/download?path=x"]]';

beforeEach(() => runTool.mockReset());

describe("a command that offers a file", () => {
  it("puts the download marker before the formatted result", async () => {
    runTool.mockResolvedValue({ text: JSON.stringify({ message: "Exported.", download_markers: [MARKER] }), isError: false });

    const out = await new SlashCommandRunner().run("/files export");

    expect(out).toBe(`${MARKER}\n\nExported.`);
  });

  it("keeps several markers in order, one per line", async () => {
    const second = MARKER.replace("a.csv", "b.csv");
    runTool.mockResolvedValue({ text: JSON.stringify({ message: "Done.", download_markers: [MARKER, second] }), isError: false });

    const out = await new SlashCommandRunner().run("/files export");

    expect(out).toBe(`${MARKER}\n${second}\n\nDone.`);
  });

  it("shows the marker list nowhere else in the result", async () => {
    runTool.mockResolvedValue({ text: JSON.stringify({ message: "Done.", download_markers: [MARKER] }), isError: false });

    const out = await new SlashCommandRunner().run("/files export");

    expect(out.split("DOWNLOAD").length - 1).toBe(1);
    expect(out.toLowerCase()).not.toContain("download markers");
  });

  it("adds nothing when the tool offers no file", async () => {
    runTool.mockResolvedValue({ text: JSON.stringify({ message: "Done." }), isError: false });

    expect(await new SlashCommandRunner().run("/files export")).toBe("Done.");
  });

  it("ignores list entries that are not markers", async () => {
    runTool.mockResolvedValue({ text: JSON.stringify({ message: "Done.", download_markers: ["x", MARKER] }), isError: false });

    expect(await new SlashCommandRunner().run("/files export")).toBe(`${MARKER}\n\nDone.`);
  });

  it("keeps the cross mark of a failed tool in front", async () => {
    runTool.mockResolvedValue({ text: JSON.stringify({ message: "Partly.", download_markers: [MARKER] }), isError: true });

    expect(await new SlashCommandRunner().run("/files export")).toBe(`❌ ${MARKER}\n\nPartly.`);
  });

  it("shows plain text output as it is", async () => {
    runTool.mockResolvedValue({ text: "plain output", isError: false });

    expect(await new SlashCommandRunner().run("/files export")).toBe("plain output");
  });
});

describe("capabilities the account has not added", () => {
  it("leaves their commands out of the list", async () => {
    const runner = new SlashCommandRunner();

    expect((await runner.list([], null)).map((c) => c.capability)).toEqual(["files"]);
    expect((await runner.list([], ["files"])).map((c) => c.capability)).toEqual(["files"]);
    expect(await runner.list([], [])).toEqual([]);
    expect(await runner.list([], ["other"])).toEqual([]);
  });

  it("refuses to run one, and says where to add it", async () => {
    const out = await new SlashCommandRunner().run("/files export", [], []);

    expect(out).toBe('❌ "files" isn\'t added to your account. Add it in the Supermarket.');
    expect(runTool).not.toHaveBeenCalled();
  });

  it("still runs the ones that are added", async () => {
    runTool.mockResolvedValue({ text: "done", isError: false });

    expect(await new SlashCommandRunner().run("/files export", [], ["files"])).toBe("done");
  });
});
