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

export interface RoleRef {
  id: number;
  name: string;
}

export interface AdminAccount {
  id: number;
  username: string;
  email: string;
  email_verified: boolean;
  is_active: boolean;
  /** The bootstrap admin: can't be edited, deleted or lose roles. */
  is_protected: boolean;
  created_at: string;
  roles: RoleRef[];
}

export interface Role {
  id: number;
  name: string;
  description: string | null;
  /** The Administrator role: can't be renamed, deleted or lose permissions. */
  is_protected: boolean;
  permissions: string[];
  account_count: number;
}

export interface PermissionInfo {
  name: string;
  description: string | null;
}

/** Counts for the Admin overview tiles. */
export interface AdminSummary {
  accounts: number | null;
  unverified: number | null;
  disabled: number | null;
  open_invites: number | null;
  roles: number | null;
}

export type AccountStatus = "all" | "unverified" | "disabled";

export interface AccountFilters {
  /** Username or email substring, case-insensitive. */
  q?: string;
  status?: AccountStatus;
}

export interface AccountChanges {
  username?: string;
  email?: string;
  is_active?: boolean;
}

export interface RoleChanges {
  /** Complete desired permission set; omitted leaves it unchanged. */
  permissions?: string[];
  name?: string;
  /** "" clears it. */
  description?: string;
}

const enc = encodeURIComponent;

/** ember_api's /api/admin routes (separate administrative permissions). */
export const adminClient = {
  listInvites: () => apiRequest<Invite[]>("GET", "/api/admin/invites"),
  createInvite: (invitee_email: string | null, delivery_method: "manual" | "email") =>
    apiRequest<CreatedInvite>("POST", "/api/admin/invites", { invitee_email, delivery_method }),
  revokeInvite: (id: number) => apiRequest<void>("DELETE", `/api/admin/invites/${id}`),

  summary: () => apiRequest<AdminSummary>("GET", "/api/admin/summary"),

  listAccounts: (filters: AccountFilters = {}) => {
    const query = new URLSearchParams();
    const q = filters.q?.trim();
    if (q) query.set("q", q);
    if (filters.status && filters.status !== "all") query.set("status", filters.status);
    const suffix = query.size ? `?${query}` : "";
    return apiRequest<AdminAccount[]>("GET", `/api/admin/accounts${suffix}`);
  },
  updateAccount: (id: number, changes: AccountChanges) =>
    apiRequest<AdminAccount>("PATCH", `/api/admin/accounts/${id}`, changes),
  deleteAccount: (id: number) => apiRequest<void>("DELETE", `/api/admin/accounts/${id}`),
  assignRole: (accountId: number, roleId: number) =>
    apiRequest<AdminAccount>("PUT", `/api/admin/accounts/${accountId}/roles/${roleId}`),
  removeRole: (accountId: number, roleId: number) =>
    apiRequest<AdminAccount>("DELETE", `/api/admin/accounts/${accountId}/roles/${roleId}`),
  sendVerification: (id: number) =>
    apiRequest<{ sent: boolean }>("POST", `/api/admin/accounts/${id}/send-verification`),

  listRoles: () => apiRequest<Role[]>("GET", "/api/admin/roles"),
  createRole: (name: string, description: string | null) =>
    apiRequest<Role>("POST", "/api/admin/roles", { name, description }),
  updateRole: (id: number, changes: RoleChanges) => apiRequest<Role>("PATCH", `/api/admin/roles/${id}`, changes),
  deleteRole: (id: number) => apiRequest<void>("DELETE", `/api/admin/roles/${id}`),
  grantPermission: (roleId: number, name: string) =>
    apiRequest<Role>("PUT", `/api/admin/roles/${roleId}/permissions/${enc(name)}`),
  revokePermission: (roleId: number, name: string) =>
    apiRequest<Role>("DELETE", `/api/admin/roles/${roleId}/permissions/${enc(name)}`),

  listPermissions: () => apiRequest<PermissionInfo[]>("GET", "/api/admin/permissions"),
};
