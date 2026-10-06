import { describe, expect, it } from "vitest";
import { MAX_FOLDERS, type ChatFolder } from "../api/FoldersClient";
import type { Conversation } from "../api/types";
import { chatMenuItems, folderMenuItems, parseChatChoice } from "./chatMenu";

const chat = (extra: Partial<Conversation> = {}): Conversation => ({
  id: "c1",
  title: "T",
  messages: [],
  createdAt: 0,
  updatedAt: 0,
  ...extra,
});
const folder = (id: number): ChatFolder => ({ id, name: `F${id}`, position: id, chat_count: 0 });
const byId = (items: ReturnType<typeof chatMenuItems>, id: string) => items.find((i) => i.id === id);

describe("chatMenuItems", () => {
  it("offers Pin, Move to..., Rename and Delete in that order", () => {
    const items = chatMenuItems(chat(), [], false).filter((i) => !i.separator);

    expect(items.map((i) => i.id)).toEqual(["pin", "move", "rename", "delete"]);
  });

  it("offers Unpin for a pinned chat", () => {
    const items = chatMenuItems(chat({ pinned: true }), [], false);

    expect(byId(items, "unpin")?.label).toBe("Unpin");
    expect(byId(items, "pin")).toBeUndefined();
  });

  it("lists No folder, the folders and New folder in the flyout, checking the current one", () => {
    const move = byId(chatMenuItems(chat({ folderId: 2 }), [folder(1), folder(2)], false), "move")!;
    const children = move.children!.filter((i) => !i.separator);

    expect(children.map((i) => i.id)).toEqual(["move:none", "move:1", "move:2", "move:new"]);
    expect(children.map((i) => !!i.checked)).toEqual([false, false, true, false]);
  });

  it("checks No folder for an unfiled chat", () => {
    const move = byId(chatMenuItems(chat(), [folder(1)], false), "move")!;

    expect(move.children!.find((i) => i.id === "move:none")?.checked).toBe(true);
  });

  it("disables Move to... and Delete while the chat is answering, but not Pin or Rename", () => {
    const items = chatMenuItems(chat(), [], true);

    expect([byId(items, "move")?.disabled, byId(items, "delete")?.disabled]).toEqual([true, true]);
    expect([byId(items, "pin")?.disabled, byId(items, "rename")?.disabled]).toEqual([undefined, undefined]);
  });

  it("disables New folder at the folder limit", () => {
    const many = Array.from({ length: MAX_FOLDERS }, (_, i) => folder(i + 1));
    const move = byId(chatMenuItems(chat(), many, false), "move")!;

    expect(move.children!.find((i) => i.id === "move:new")?.disabled).toBe(true);
  });

  it("marks Delete as dangerous", () => {
    expect(byId(chatMenuItems(chat(), [], false), "delete")?.danger).toBe(true);
  });
});

describe("folderMenuItems", () => {
  it("offers Rename and Delete", () => {
    expect(folderMenuItems(false).map((i) => i.id)).toEqual(["rename", "delete"]);
  });

  it("can switch Delete off, leaving Rename on", () => {
    const items = folderMenuItems(true);

    expect(items.find((i) => i.id === "delete")?.disabled).toBe(true);
    expect(items.find((i) => i.id === "rename")?.disabled).toBeFalsy();
    expect(folderMenuItems(false).find((i) => i.id === "delete")?.disabled).toBeFalsy();
  });
});

describe("parseChatChoice", () => {
  it("reads the simple actions", () => {
    expect(parseChatChoice("pin")).toEqual({ action: "pin" });
    expect(parseChatChoice("unpin")).toEqual({ action: "unpin" });
    expect(parseChatChoice("rename")).toEqual({ action: "rename" });
    expect(parseChatChoice("delete")).toEqual({ action: "delete" });
  });

  it("reads the move choices", () => {
    expect(parseChatChoice("move:none")).toEqual({ action: "move", folderId: null });
    expect(parseChatChoice("move:7")).toEqual({ action: "move", folderId: 7 });
    expect(parseChatChoice("move:new")).toEqual({ action: "moveNew" });
  });

  it("returns null for anything else", () => {
    expect(parseChatChoice("move")).toBeNull();
    expect(parseChatChoice("move:abc")).toBeNull();
    expect(parseChatChoice("")).toBeNull();
  });
});
