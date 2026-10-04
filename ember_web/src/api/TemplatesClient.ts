import { apiRequest } from "./http";

/** A saved prompt, as ember_api stores it (private to the account). Times are naive UTC. */
export interface PromptTemplate {
  id: number;
  name: string;
  body: string;
  created_at: string;
  updated_at: string;
}

// The limits ember_api enforces (services/template_service.py).
export const TEMPLATE_NAME_MAX = 60;
export const TEMPLATE_BODY_MAX = 10_000;

const path = (id: number) => `/api/templates/${id}`;

/** ember_api's /api/templates routes (chat.use). */
export const templatesClient = {
  /** Most recently edited first. */
  list: () => apiRequest<PromptTemplate[]>("GET", "/api/templates"),
  create: (name: string, body: string) => apiRequest<PromptTemplate>("POST", "/api/templates", { name, body }),
  update: (id: number, name: string, body: string) => apiRequest<PromptTemplate>("PUT", path(id), { name, body }),
  remove: (id: number) => apiRequest<void>("DELETE", path(id)),
};
