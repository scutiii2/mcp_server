import { describe, expect, it } from "vitest";
import { downloadHref, downloadMarkersOf, formatFileSize, hideDownloadMarkers, parseDownloads } from "./downloads";

const marker = (extra = "") => `[[DOWNLOAD filename="wo.txt" bytes="5" url="/server/download?path=x" ${extra}]]`.replace(" ]]", "]]");
const plain = '[[DOWNLOAD filename="wo.txt" bytes="5" url="/server/download?path=x"]]';
const labelled = '[[DOWNLOAD filename="wo.txt" bytes="5" url="/server/download?path=x" label="EXPORT"]]';

describe("downloadHref", () => {
  it("sends a mcp_server download through ember_api", () => {
    expect(downloadHref("/server/download?path=%2Fsrv%2Fa.csv")).toBe("/api/server/download?path=%2Fsrv%2Fa.csv");
  });

  it("keeps a URL that already points at ember_api", () => {
    expect(downloadHref("/api/server/download?path=x")).toBe("/api/server/download?path=x");
  });

  it.each([
    "https://evil.example/file",
    "//evil.example/file",
    "/server/other?path=x",
    "/server/download",
    "/api/other",
    "javascript:alert(1)",
    "data:text/html,x",
    "/server/download?path=x\\y",
    "/server/download?path=x\ny",
    "/server/download?path=x\u0000y",
    "/server/download?path=x\u001fy",
    "",
    "server/download?path=x",
    "/Server/download?path=x",
  ])("refuses %j", (url) => {
    expect(downloadHref(url)).toBeNull();
  });
});

describe("parseDownloads", () => {
  it("takes a marker out of the text and makes a card", () => {
    expect(parseDownloads(`Done.\n\n${plain}`)).toEqual({
      text: "Done.",
      downloads: [{ filename: "wo.txt", bytes: 5, href: "/api/server/download?path=x", label: "DOWNLOAD" }],
    });
  });

  it("reads the label when there is one", () => {
    expect(parseDownloads(labelled).downloads[0]!.label).toBe("EXPORT");
  });

  it("makes a card for each marker, in order", () => {
    const text = `${plain}\n${marker().replace("wo.txt", "b.txt")}\nBody`;

    const parsed = parseDownloads(text);

    expect(parsed.downloads.map((d) => d.filename)).toEqual(["wo.txt", "b.txt"]);
    expect(parsed.text).toBe("Body");
  });

  it("returns the text untouched, not trimmed, when there is no marker", () => {
    expect(parseDownloads("  hello  \n")).toEqual({ text: "  hello  \n", downloads: [] });
  });

  it("keeps a card whose URL is not allowed but gives it no link", () => {
    const parsed = parseDownloads('[[DOWNLOAD filename="a.exe" bytes="9" url="https://evil.example/a.exe"]]');

    expect(parsed.downloads).toEqual([{ filename: "a.exe", bytes: 9, href: null, label: "DOWNLOAD" }]);
    expect(parsed.text).toBe("");
  });

  it("leaves a half-written or different marker as text", () => {
    expect(parseDownloads('[[DOWNLOAD filename="a"').downloads).toEqual([]);
    expect(parseDownloads("[[ATTACHMENT filename=\"a\"]]").downloads).toEqual([]);
  });

  it("does not remember the last match between calls", () => {
    expect(parseDownloads(plain).downloads).toHaveLength(1);
    expect(parseDownloads(plain).downloads).toHaveLength(1);
  });
});

describe("hideDownloadMarkers", () => {
  it("removes a complete marker", () => {
    expect(hideDownloadMarkers(`A ${plain} B`)).toBe("A  B");
  });

  it.each([
    ["Text [[", "Text"],
    ["Text [[DOW", "Text"],
    ["Text [[DOWNLOAD", "Text"],
    ['Text [[DOWNLOAD filename="a" by', "Text"],
  ])("hides a marker that is still being typed: %j", (streamed, shown) => {
    expect(hideDownloadMarkers(streamed)).toBe(shown);
  });

  it("keeps other double brackets", () => {
    expect(hideDownloadMarkers("see [[wiki link]] here")).toBe("see [[wiki link]] here");
    expect(hideDownloadMarkers("see [[other")).toBe("see [[other");
  });

  it("keeps a single trailing bracket", () => {
    expect(hideDownloadMarkers("items [")).toBe("items [");
  });

  it("keeps a finished marker that is not a real download marker", () => {
    expect(hideDownloadMarkers("[[DOWNLOAD x]] tail")).toBe("[[DOWNLOAD x]] tail");
  });

  it("keeps text with no brackets as it is", () => {
    expect(hideDownloadMarkers("plain text ")).toBe("plain text ");
  });

  it("hides an unfinished marker after a finished one", () => {
    expect(hideDownloadMarkers(`${plain}\nNext [[DOWNLOAD fi`)).toBe("\nNext");
  });
});

describe("formatFileSize", () => {
  it.each([
    [0, ""],
    [1, "1 KB"],
    [1024, "1 KB"],
    [1025, "2 KB"],
    [1024 * 1024 - 1, "1024 KB"],
    [1024 * 1024, "1.0 MB"],
    [1_572_864, "1.5 MB"],
  ])("%d bytes is %j", (bytes, text) => {
    expect(formatFileSize(bytes)).toBe(text);
  });
});

describe("downloadMarkersOf", () => {
  it("lists the markers of a tool result", () => {
    const result = JSON.stringify({ message: "ok", download_markers: [plain, labelled] });

    expect(downloadMarkersOf(result)).toEqual([plain, labelled]);
  });

  it("skips anything in the list that is not a marker", () => {
    const result = JSON.stringify({ download_markers: ["just text", 5, null, ` ${plain} `, "[[DOWNLOAD x]]"] });

    expect(downloadMarkersOf(result)).toEqual([plain]);
  });

  it.each([
    "plain text",
    "[1, 2]",
    "{not json",
    "{}",
    '{"download_markers": "not a list"}',
    '{"download_markers": null}',
    "",
  ])("finds none in %j", (text) => {
    expect(downloadMarkersOf(text)).toEqual([]);
  });

  it("tolerates leading whitespace", () => {
    expect(downloadMarkersOf(`  ${JSON.stringify({ download_markers: [plain] })}`)).toEqual([plain]);
  });
});
