import { apiRequest } from "./http";

/** The logged-in account, as ember_api's /api/auth routes return it. */
export interface Account {
  id: number;
  username: string;
  email: string;
  email_verified: boolean;
  roles: string[];
  permissions: string[];
}

export interface RegisterResult {
  account: Account;
  /** False when SMTP failed; the account exists and resend can retry. */
  verification_email_sent: boolean;
  email_error: string | null;
}

export interface RegisterInput {
  username: string;
  email: string;
  password: string;
  invite_code: string;
}

/** ember_api's /api/auth routes. Stateless; the auth store holds the account. */
export const authClient = {
  me: () => apiRequest<Account>("GET", "/api/auth/me"),
  login: (username: string, password: string) =>
    apiRequest<Account>("POST", "/api/auth/login", { username, password }),
  logout: () => apiRequest<void>("POST", "/api/auth/logout"),
  register: (input: RegisterInput) => apiRequest<RegisterResult>("POST", "/api/auth/register", input),
  verifyEmail: (code: string) => apiRequest<Account>("POST", "/api/auth/verify-email", { code }),
  resendVerification: () => apiRequest<{ sent: boolean }>("POST", "/api/auth/verify-email/resend"),
};
