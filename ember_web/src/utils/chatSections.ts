import type { ChatFolder } from "../api/FoldersClient";
import type { Conversation } from "../api/types";

/** One block of the chat list: the pinned chats, one folder, or the chats in no folder. */
export interface ChatSection {
  kind: "pinned" | "folder" | "unfiled";
  key: string;
  /** Set for a folder section. */
  folder: ChatFolder | null;
  chats: Conversation[];
}

export interface ChatLayout {
  /** False with no pins and no folders: one flat list, shown without headers. */
  grouped: boolean;
  sections: ChatSection[];
}

/** Sorts `chats` (already in display order) into Pinned, the folders in the
 * order given, then Unfiled. Folders always appear, even empty; Pinned and
 * Unfiled only when they hold chats. A chat in a folder this list does not
 * know (not loaded yet, or deleted elsewhere) counts as unfiled. While dragging,
 * a grouped list also shows empty Pinned and Chats sections as drop zones. */
export function buildLayout(chats: Conversation[], folders: ChatFolder[], dragging = false): ChatLayout {
  const known = new Set(folders.map((f) => f.id));
  const pinned: Conversation[] = [];
  const unfiled: Conversation[] = [];
  const byFolder = new Map<number, Conversation[]>();

  for (const chat of chats) {
    if (chat.pinned) {
      pinned.push(chat);
    } else if (chat.folderId != null && known.has(chat.folderId)) {
      const list = byFolder.get(chat.folderId);
      if (list) list.push(chat);
      else byFolder.set(chat.folderId, [chat]);
    } else {
      unfiled.push(chat);
    }
  }

  if (pinned.length === 0 && folders.length === 0) {
    return { grouped: false, sections: [{ kind: "unfiled", key: "unfiled", folder: null, chats: unfiled }] };
  }

  const sections: ChatSection[] = [];
  if (pinned.length > 0 || dragging) sections.push({ kind: "pinned", key: "pinned", folder: null, chats: pinned });
  for (const folder of folders) {
    sections.push({ kind: "folder", key: `folder-${folder.id}`, folder, chats: byFolder.get(folder.id) ?? [] });
  }
  if (unfiled.length > 0 || dragging) sections.push({ kind: "unfiled", key: "unfiled", folder: null, chats: unfiled });
  return { grouped: true, sections };
}
