import { apiRequest } from "./http";

/** A chat folder as ember_api lists it (private to the account). */
export interface ChatFolder {
  id: number;
  name: string;
  /** Display order, lowest first; ties are broken by id. */
  position: number;
  chat_count: number;
}

// The limits ember_api enforces (services/folder_service.py).
export const FOLDER_NAME_MAX = 60;
export const MAX_FOLDERS = 30;

const path = (id: number) => `/api/chat-folders/${id}`;

/** ember_api's /api/chat-folders routes (chat.use). */
export const foldersClient = {
  /** In display order. */
  list: () => apiRequest<ChatFolder[]>("GET", "/api/chat-folders"),
  create: (name: string) => apiRequest<ChatFolder>("POST", "/api/chat-folders", { name }),
  rename: (id: number, name: string) => apiRequest<ChatFolder>("PATCH", path(id), { name }),
  reorder: (id: number, position: number) => apiRequest<ChatFolder>("PATCH", path(id), { position }),
  /** Moves one place in display order, saved atomically. */
  move: (id: number, direction: "up" | "down") => apiRequest<ChatFolder>("PATCH", path(id), { direction }),
  /** Deletes the folder and every chat in it; refused while one of them is answering. */
  remove: (id: number) => apiRequest<void>("DELETE", path(id)),
};
