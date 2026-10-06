import type { Conversation } from "../api/types";

/** Where a dragged chat was dropped. */
export type DropTarget = { kind: "pinned" } | { kind: "folder"; folderId: number } | { kind: "unfiled" };

/** One change a drop makes; `move` always comes before `pin`. */
export type DropOp = { op: "move"; folderId: number | null } | { op: "pin"; pinned: boolean };

/** What dropping `chat` on `target` changes (nothing: an empty list, and the
 * target does not accept the drop). The target decides the placement, so the
 * chat always shows up where it was dropped: a folder or Chats also unpins it,
 * Pinned pins it and leaves its folder alone. */
export function dropOps(chat: Conversation, target: DropTarget): DropOp[] {
  const folderId = chat.folderId ?? null;
  const ops: DropOp[] = [];
  switch (target.kind) {
    case "folder":
      if (folderId !== target.folderId) ops.push({ op: "move", folderId: target.folderId });
      if (chat.pinned) ops.push({ op: "pin", pinned: false });
      break;
    case "unfiled":
      if (folderId !== null) ops.push({ op: "move", folderId: null });
      if (chat.pinned) ops.push({ op: "pin", pinned: false });
      break;
    case "pinned":
      if (!chat.pinned) ops.push({ op: "pin", pinned: true });
      break;
  }
  return ops;
}
