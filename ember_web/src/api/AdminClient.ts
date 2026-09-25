import { apiRequest } from "./http";

export interface Invite {
  id: number;
  invitee_email: string | null;
  delivery_method: "manual" | "email";
  created_at: string;
  expires_at: string;
}

export interface CreatedInvite {
  invite: Invite;
  /** Shown once: ember_api stores only its hash. */
  code: string;
  email_sent: boolean;
  email_error: string | null;
}

/** ember_api's /api/admin routes (admin.manage). */
export const adminClient = {
  listInvites: () => apiRequest<Invite[]>("GET", "/api/admin/invites"),
  createInvite: (invitee_email: string | null, delivery_method: "manual" | "email") =>
    apiRequest<CreatedInvite>("POST", "/api/admin/invites", { invitee_email, delivery_method }),
};
