import { describe, expect, it } from "vitest";
import type { ChatFolder } from "../api/FoldersClient";
import type { Conversation } from "../api/types";
import { buildLayout } from "./chatSections";

const chat = (id: string, extra: Partial<Conversation> = {}): Conversation => ({
  id,
  title: id,
  messages: [],
  createdAt: 0,
  updatedAt: 0,
  ...extra,
});
const folder = (id: number, name = `F${id}`): ChatFolder => ({ id, name, position: id, chat_count: 0 });
const ids = (chats: Conversation[]) => chats.map((c) => c.id);

describe("buildLayout", () => {
  it("is flat, with no headers, when there are no pins and no folders", () => {
    const layout = buildLayout([chat("a"), chat("b")], []);

    expect(layout.grouped).toBe(false);
    expect(layout.sections).toHaveLength(1);
    expect(layout.sections[0]).toMatchObject({ kind: "unfiled" });
    expect(ids(layout.sections[0]!.chats)).toEqual(["a", "b"]);
  });

  it("puts pinned chats first, then folders in order, then the rest", () => {
    const layout = buildLayout(
      [chat("p", { pinned: true }), chat("in2", { folderId: 2 }), chat("in1", { folderId: 1 }), chat("free")],
      [folder(1), folder(2)],
    );

    expect(layout.grouped).toBe(true);
    expect(layout.sections.map((s) => s.key)).toEqual(["pinned", "folder-1", "folder-2", "unfiled"]);
    expect(layout.sections.map((s) => ids(s.chats))).toEqual([["p"], ["in1"], ["in2"], ["free"]]);
  });

  it("shows a pinned chat only in Pinned, whatever folder it is in", () => {
    const layout = buildLayout([chat("p", { pinned: true, folderId: 1 })], [folder(1)]);

    expect(layout.sections.map((s) => ids(s.chats))).toEqual([["p"], []]);
  });

  it("always shows folders, even empty ones, and hides empty Pinned and Unfiled", () => {
    const layout = buildLayout([], [folder(1)]);

    expect(layout.grouped).toBe(true);
    expect(layout.sections.map((s) => s.key)).toEqual(["folder-1"]);
    expect(layout.sections[0]!.folder?.name).toBe("F1");
  });

  it("treats undefined, null and unknown folders as unfiled", () => {
    const layout = buildLayout(
      [chat("a"), chat("b", { folderId: null }), chat("c", { folderId: 99 })],
      [folder(1)],
    );

    expect(layout.sections.map((s) => s.key)).toEqual(["folder-1", "unfiled"]);
    expect(ids(layout.sections[1]!.chats)).toEqual(["a", "b", "c"]);
  });

  it("keeps the order it was given inside a section", () => {
    const layout = buildLayout([chat("z", { folderId: 1 }), chat("y", { folderId: 1 })], [folder(1)]);

    expect(ids(layout.sections[0]!.chats)).toEqual(["z", "y"]);
  });

  it("adds empty Chats and Pinned drop zones below the folders while dragging with nothing pinned", () => {
    const layout = buildLayout([chat("a", { folderId: 1 })], [folder(1)], true);

    expect(layout.sections.map((s) => s.key)).toEqual(["folder-1", "unfiled", "pinned"]);
    expect(layout.sections[1]!.chats).toEqual([]);
    expect(layout.sections[2]!.chats).toEqual([]);
  });

  it("keeps Pinned on top while dragging when it holds chats", () => {
    const layout = buildLayout([chat("p", { pinned: true }), chat("a", { folderId: 1 })], [folder(1)], true);

    expect(layout.sections.map((s) => s.key)).toEqual(["pinned", "folder-1", "unfiled"]);
  });

  it("does not duplicate Pinned or Chats while dragging when they already have chats", () => {
    const layout = buildLayout([chat("p", { pinned: true }), chat("free")], [folder(1)], true);

    expect(layout.sections.map((s) => s.key)).toEqual(["pinned", "folder-1", "unfiled"]);
    expect(layout.sections.map((s) => s.chats.length)).toEqual([1, 0, 1]);
  });

  it("leaves the flat list alone while dragging", () => {
    const layout = buildLayout([chat("a"), chat("b")], [], true);

    expect(layout.grouped).toBe(false);
    expect(layout.sections).toHaveLength(1);
  });
});
