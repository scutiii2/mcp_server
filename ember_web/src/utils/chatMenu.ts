import { MAX_FOLDERS, type ChatFolder } from "../api/FoldersClient";
import type { Conversation } from "../api/types";

/** One line of a popup menu. `children` makes it open a flyout. */
export interface MenuItem {
  id: string;
  label: string;
  checked?: boolean;
  danger?: boolean;
  disabled?: boolean;
  separator?: boolean;
  children?: MenuItem[];
}

const separator = (id: string): MenuItem => ({ id, label: "", separator: true });

/** The menu of a chat row. `answering`: an answer is being written for this
 * chat, so it can be neither moved nor deleted (pinning and renaming change
 * no messages and stay available). */
export function chatMenuItems(chat: Conversation, folders: ChatFolder[], answering: boolean): MenuItem[] {
  const current = chat.folderId ?? null;
  const flyout: MenuItem[] = [
    { id: "move:none", label: "No folder", checked: current === null },
    ...folders.map((f) => ({ id: `move:${f.id}`, label: f.name, checked: current === f.id })),
    separator("sep-new"),
    { id: "move:new", label: "New folder...", disabled: folders.length >= MAX_FOLDERS },
  ];
  return [
    chat.pinned ? { id: "unpin", label: "Unpin" } : { id: "pin", label: "Pin" },
    { id: "move", label: "Move to...", disabled: answering, children: flyout },
    separator("sep-edit"),
    { id: "rename", label: "Rename" },
    { id: "delete", label: "Delete", danger: true, disabled: answering },
  ];
}

/** The menu of a folder header. */
export function folderMenuItems(): MenuItem[] {
  return [
    { id: "rename", label: "Rename" },
    { id: "delete", label: "Delete", danger: true },
  ];
}

export type ChatChoice =
  | { action: "pin" | "unpin" | "rename" | "delete" }
  | { action: "move"; folderId: number | null }
  | { action: "moveNew" };

/** Turns a chat-menu item id back into what the user chose. */
export function parseChatChoice(id: string): ChatChoice | null {
  if (id === "pin" || id === "unpin" || id === "rename" || id === "delete") return { action: id };
  if (id === "move:none") return { action: "move", folderId: null };
  if (id === "move:new") return { action: "moveNew" };
  const match = /^move:(\d+)$/.exec(id);
  return match ? { action: "move", folderId: Number(match[1]) } : null;
}
