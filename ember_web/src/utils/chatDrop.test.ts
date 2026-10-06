import { describe, expect, it } from "vitest";
import type { Conversation } from "../api/types";
import { dropOps } from "./chatDrop";

const chat = (extra: Partial<Conversation> = {}): Conversation => ({
  id: "c1",
  title: "T",
  messages: [],
  createdAt: 0,
  updatedAt: 0,
  ...extra,
});

describe("dropOps", () => {
  it("moves an unfiled chat into a folder", () => {
    expect(dropOps(chat(), { kind: "folder", folderId: 2 })).toEqual([{ op: "move", folderId: 2 }]);
  });

  it("moves a chat from one folder to another", () => {
    expect(dropOps(chat({ folderId: 1 }), { kind: "folder", folderId: 2 })).toEqual([{ op: "move", folderId: 2 }]);
  });

  it("does nothing for a chat dropped on the folder it is already in", () => {
    expect(dropOps(chat({ folderId: 2 }), { kind: "folder", folderId: 2 })).toEqual([]);
  });

  it("unpins a pinned chat dropped on a folder, moving it first", () => {
    expect(dropOps(chat({ pinned: true, folderId: 1 }), { kind: "folder", folderId: 2 })).toEqual([
      { op: "move", folderId: 2 },
      { op: "pin", pinned: false },
    ]);
  });

  it("only unpins a pinned chat dropped on the folder it is already filed in", () => {
    expect(dropOps(chat({ pinned: true, folderId: 2 }), { kind: "folder", folderId: 2 })).toEqual([
      { op: "pin", pinned: false },
    ]);
  });

  it("pins a chat dropped on Pinned and keeps its folder", () => {
    expect(dropOps(chat({ folderId: 3 }), { kind: "pinned" })).toEqual([{ op: "pin", pinned: true }]);
  });

  it("does nothing for a pinned chat dropped on Pinned", () => {
    expect(dropOps(chat({ pinned: true }), { kind: "pinned" })).toEqual([]);
  });

  it("takes a chat out of its folder when dropped on Chats", () => {
    expect(dropOps(chat({ folderId: 3 }), { kind: "unfiled" })).toEqual([{ op: "move", folderId: null }]);
  });

  it("takes a pinned, filed chat out of both when dropped on Chats", () => {
    expect(dropOps(chat({ pinned: true, folderId: 3 }), { kind: "unfiled" })).toEqual([
      { op: "move", folderId: null },
      { op: "pin", pinned: false },
    ]);
  });

  it("does nothing for an unfiled, unpinned chat dropped on Chats", () => {
    expect(dropOps(chat(), { kind: "unfiled" })).toEqual([]);
    expect(dropOps(chat({ folderId: null }), { kind: "unfiled" })).toEqual([]);
  });
});
